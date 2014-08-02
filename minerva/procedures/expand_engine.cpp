#include <iostream>
#include <vector>
#include <tuple>
#include <glog/logging.h>

#include "expand_engine.h"
#include "system/minerva_system.h"

using namespace std;

namespace minerva {

void ExpandEngine::Process(LogicalDag& dag, const std::vector<uint64_t>& nodes) {
  for(uint64_t nid : nodes) {
    ExpandNode(dag, nid);
  }
}

NVector<uint64_t> ExpandEngine::GetPhysicalNodes(uint64_t id) const {
  auto it = lnode_to_pnode_.find(id);
  CHECK(it != lnode_to_pnode_.end()) << "invalid physical nid: " << id;
  return it->second;
}

void ExpandEngine::ExpandNode(LogicalDag& dag, uint64_t lnid) {
  if(lnode_to_pnode_.find(lnid) == lnode_to_pnode_.end()) { // haven't been expanded yet
    DagNode* curnode = dag.GetNode(lnid);
    //cout << "Try expand nodeid=" << lnid << " " << curnode->Type() << endl;
    for(DagNode* pred : curnode->predecessors_) {
      ExpandNode(dag, pred->node_id_);
    }
    if(curnode->Type() == DagNode::DATA_NODE) { // data node
      LogicalDag::DNode* dnode = dynamic_cast<LogicalDag::DNode*>(curnode);
      // call expand function to generate data
      LogicalDataGenFn* fn = dnode->data_.data_gen_fn;
      if(fn != NULL) {
        LOG(INFO) << "Expand logical datagen function: " << fn->Name();
        NVector<Scale> partsizes = dnode->data_.partitions.Map<Scale>(
            [] (const PartInfo& pi) { return pi.size; }
          );
        NVector<Chunk> chunks = fn->Expand(partsizes);
        MakeMapping(dnode, chunks);
      }
    }
    else { // op node
      LogicalDag::ONode* onode = dynamic_cast<LogicalDag::ONode*>(curnode);
      LogicalComputeFn* fn = onode->op_.compute_fn;
      CHECK_NOTNULL(fn);
      // make input chunks
      std::vector<NVector<Chunk>> in_chunks;
      for(LogicalDag::DNode* dn : onode->inputs_) {
        NVector<uint64_t> mapped_pnode_ids = lnode_to_pnode_[dn->node_id_];
        in_chunks.push_back(
          mapped_pnode_ids.Map<Chunk>(
            [] (const uint64_t& nid) {
              PhysicalDag::DNode* pnode = MinervaSystem::Instance().physical_dag().GetDataNode(nid);
              return Chunk(pnode);
            }
          )
        );
      }
      // call expand function
      LOG(INFO) << "Expand logical compute function: " << fn->Name();
      std::vector<NVector<Chunk>> rst_chunks = fn->Expand(in_chunks);
      // check output validity
      CHECK_EQ(rst_chunks.size(), onode->outputs_.size()) 
        << "Expand function error: #output unmatched. Function name: " << fn->Name();
      for(size_t i = 0; i < rst_chunks.size(); ++i) {
        MakeMapping(onode->outputs_[i], rst_chunks[i]);
      }
    }
  }
}

void ExpandEngine::MakeMapping(LogicalDag::DNode* ldnode, const NVector<Chunk>& chunks) {
  Scale numparts = chunks.Size();
  size_t numdims = numparts.NumDims();
  // check size
  NVector<Scale> chunk_sizes = chunks.Map<Scale>( [] (const Chunk& ch) { return ch.Size(); } );
  Scale merged_size = Scale::Merge(chunk_sizes);
  CHECK_EQ(ldnode->data_.size, merged_size)
    << "Expand function error: partition size unmatched!\n"
    << "Expected: " << ldnode->data_.size << "\n"
    << "Got: " << merged_size;
  // offset & offset_index
  Scale pos = Scale::Origin(numdims);
  chunks[pos].data_node()->data_.offset = pos; // the offset of first chunk is zero
  do {
    auto& phy_data = chunks[pos].data_node()->data_;
    phy_data.offset_index = pos;
    Scale upleftpos = pos.Map([] (int x) { return max(x - 1, 0); });
    auto& upleft_phy_data = chunks[upleftpos].data_node()->data_;
    phy_data.offset = upleft_phy_data.offset + upleft_phy_data.size;
    for(size_t i = 0; i < numdims; ++i) {
      if(pos[i] == 0) { // if the index of this dimension is 0, then so does the offset
        phy_data.offset[i] = 0;
      }
    }
  } while(Scale::IncrOne(pos, numparts));
  // insert mapping
  lnode_to_pnode_[ldnode->node_id_] = chunks.Map<uint64_t>(
      [&] (const Chunk& ch) {
        return ch.data_node()->node_id_;
      }
    );
}

} // end of namespace minerva