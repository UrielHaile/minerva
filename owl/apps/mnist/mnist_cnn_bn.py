import sys
import time
import argparse
import numpy as np
import mnist_io
import owl
import owl.elewise as ele
import owl.conv as conv

lazy_cycle = 4

class MNISTCNNModel:
    def __init__(self):
        self.convs = [
            conv.Convolver(0, 0, 1, 1),
            conv.Convolver(2, 2, 1, 1),
        ];
        self.poolings = [
            conv.Pooler(2, 2, 2, 2, 0, 0, conv.pool_op.max),
            conv.Pooler(3, 3, 3, 3, 0, 0, conv.pool_op.max)
        ];

    def init_random(self):
        self.weights = [
            owl.randn([5, 5, 1, 16], 0.0, 0.1),
            owl.randn([5, 5, 16, 32], 0.0, 0.1),
            owl.randn([10, 512], 0.0, 0.1)
        ];
        self.weightdelta = [
            owl.zeros([5, 5, 1, 16]),
            owl.zeros([5, 5, 16, 32]),
            owl.zeros([10, 512])
        ];
        self.bias = [
            owl.zeros([16]),
            owl.zeros([32]),
            owl.zeros([10, 1])
        ];
        self.biasdelta = [
            owl.zeros([16]),
            owl.zeros([32]),
            owl.zeros([10, 1])
        ];
        #batch norm bias
        self.bias_bn = [
            owl.zeros([16]),
            owl.zeros([32]),
            owl.zeros([10, 1])
        ];
        self.biasdelta_bn = [
            owl.zeros([16]),
            owl.zeros([32]),
            owl.zeros([10, 1])
        ];
        self.biasgrad_bn = [
            owl.zeros([16]),
            owl.zeros([32]),
            owl.zeros([10, 1])
        ];
        self.weights_bn = [
            owl.randn([1, 1, 16, 1], 0.0, 0.1),
            owl.randn([1, 1, 32, 1], 0.0, 0.1),
            owl.randn([1, 10], 0.0, 0.1)
        ];
        self.weightdelta_bn = [
            owl.zeros([5, 5, 1, 16]),
            owl.zeros([5, 5, 16, 32]),
            owl.zeros([10, 512])
        ];
        self.weightgrad_bn = [
            owl.zeros([5, 5, 1, 16]),
            owl.zeros([5, 5, 16, 32]),
            owl.zeros([10, 512])
        ];


def print_training_accuracy(o, t, mbsize, prefix):
    predict = o.reshape([10, mbsize]).max_index(0)
    ground_truth = t.reshape([10, mbsize]).max_index(0)
    correct = (predict - ground_truth).count_zero()
    print prefix, 'error: {}'.format((mbsize - correct) * 1.0 / mbsize)

def bpprop(model, samples, label):
    num_layers = 6
    num_samples = samples.shape[-1]
    fc_shape = [512, num_samples]

    acts = [None] * num_layers
    #batch norm usage
    acts_before = [None] * num_layers
    acts_after = [None] * num_layers
    exp_ = [None] * num_layers
    var_ = [None] * num_layers
    scale_ = [None] * num_layers

    errs = [None] * num_layers
    weightgrad = [None] * len(model.weights)
    biasgrad = [None] * len(model.bias)

    #epslon for batch norm
    eps_ = 1e-10


    acts[0] = samples

    #batch norm
    #note all bias should be zero, we don't add bias after norm
    acts_before[1] = model.convs[0].ff(acts[0], model.weights[0], model.bias[0])
    scale_[1] = 1.0 / np.prod(acts_before[1].shape) * acts_before[1].shape[2]
    exp_[1] = scale_[1] * acts_before[1].sumallexceptdim(2)
    var_[1] = scale_[1] * (acts_before[1] - exp_[1]) * (acts_before[1] - exp_[1])

    print exp_[1].shape
    print var_[1].shape

    acts_after[1] = ele.mult((acts_before[1] - exp_[1]), ele.pow(ele.mult(var_[1], var_[1]) + eps_, -0.5))
    acts[1] = ele.mult(acts_after[1], model.weight_bn[0]) + model.bias_bn[0]
    acts[1] = ele.sigm(acts[1])
   
    #pooling
    acts[2] = model.poolings[0].ff(acts[1])
   
    #batch norm
    #note all bias should be zero, we don't add bias after norm
    acts_before[3] = model.convs[1].ff(acts[2], model.weights[1], model.bias[1])
    scale_[3] = 1.0 / np.prod(acts_before[3].shape) * acts_before[3].shape[2]
    exp_[3] = scale_[3] * acts_before[3].sumallexceptdim(2)
    var_[3] = scale_[3] * (acts_before[3] - exp_[3]) * (acts_before[3] - exp_[3])
    acts_after[3] = ele.mult((acts_before[3] - exp_[3]), ele.pow(ele.mult(var_[3], var_[3]) + eps_, -0.5))
    acts[3] = ele.mult(acts_after[3], model.weight_bn[1]) + model.bias_bn[1]
    acts[3] = ele.sigm(acts[3])

    #pooling
    acts[4] = model.poolings[1].ff(acts[3])
    #fully
    acts[5] = model.weights[2] * acts[4].reshape(fc_shape) + model.bias[2]
    #softmax
    out = conv.softmax(acts[5], conv.soft_op.instance)

    errs[5] = out - label
    errs[4] = (model.weights[2].trans() * errs[5]).reshape(acts[4].shape)
    errs[3] = ele.sigm_back(model.poolings[1].bp(errs[4], acts[4], acts[3]), acts[3])
    
    #batchnorm bp
    gy_ = errs[3]
    gx_norm = ele.mult(errs[3], model.weights_bn[1]) 
    gvar_ = ele.mult(ele.mult(acts_before[3] - exp_[3], gx_norm).sumallexceptdim(2), -0.5 * ele.pow(ele.mult(var_[3], var_[3]) + eps_, -1.5));
    gexp_ = (gx_norm, -1 * ele.pow(ele.mult(var_[3], var_[3]) + eps_, -0.5)).sumallexceptdim(2) + ele.mult(gvar_, -2 * scale_ * (acts_before[3] - exp_[3]).sumallexceptdim(2)) 
    error[3] = ele.mult(gx_norm, -1 * ele.pow(ele.mult(var_[3], var_[3]) + eps_, -0.5)) + ele.mult(2 * scale_ * (acts_before[3] - exp_[3]), gvar_) + scale_ * gexp_ 
    model.weightgrad_bn[1] = ele.mult(gy_, acts_after[3]).sumallexceptdim(2)
    model.biasgrad_bn[1] = gy_.sumallexceptdim(2)


    exit(1)

    errs[2] = model.convs[1].bp(errs[3], acts[2], model.weights[1])
    errs[1] = ele.sigm_back(model.poolings[0].bp(errs[2], acts[2], acts[1]), acts[1])

    weightgrad[2] = errs[5] * acts[4].reshape(fc_shape).trans()
    biasgrad[2] = errs[5].sum(1)
    weightgrad[1] = model.convs[1].weight_grad(errs[3], acts[2], model.weights[1])
    biasgrad[1] = model.convs[1].bias_grad(errs[3])
    weightgrad[0] = model.convs[0].weight_grad(errs[1], acts[0], model.weights[0])
    biasgrad[0] = model.convs[0].bias_grad(errs[1])
    return (out, weightgrad, biasgrad)

def train_network(model, num_epochs=100, minibatch_size=256, lr=0.01, mom=0.75, wd=5e-4):
    # load data
    (train_data, test_data) = mnist_io.load_mb_from_mat('mnist_all.mat', minibatch_size / len(gpu))
    num_test_samples = test_data[0].shape[0]
    test_samples = owl.from_numpy(test_data[0]).reshape([28, 28, 1, num_test_samples])
    test_labels = owl.from_numpy(test_data[1])
    for i in xrange(num_epochs):
        print "---Epoch #", i
        last = time.time()
        count = 0
        weightgrads = [None] * len(gpu)
        biasgrads = [None] * len(gpu)
        for (mb_samples, mb_labels) in train_data:
            count += 1
            current_gpu = count % len(gpu)
            owl.set_device(gpu[current_gpu])
            num_samples = mb_samples.shape[0]
            data = owl.from_numpy(mb_samples).reshape([28, 28, 1, num_samples])
            label = owl.from_numpy(mb_labels)
            out, weightgrads[current_gpu], biasgrads[current_gpu] = bpprop(model, data, label)
            if current_gpu == 0:
                for k in range(len(model.weights)):
                    model.weightdelta[k] = mom * model.weightdelta[k] - lr / num_samples / len(gpu) * multi_gpu_merge(weightgrads, 0, k) - lr * wd * model.weights[k]
                    model.biasdelta[k] = mom * model.biasdelta[k] - lr / num_samples / len(gpu) * multi_gpu_merge(biasgrads, 0, k)
                    model.weights[k] += model.weightdelta[k]
                    model.bias[k] += model.biasdelta[k]
                if count % (len(gpu) * lazy_cycle) == 0:
                    print_training_accuracy(out, label, num_samples, 'Training')
        print '---End of Epoch #', i, 'time:', time.time() - last
        # do test
        out, _, _  = bpprop(model, test_samples, test_labels)
        print_training_accuracy(out, test_labels, num_test_samples, 'Testing')

def multi_gpu_merge(l, base, layer):
    if len(l) == 1:
        return l[0][layer]
    left = multi_gpu_merge(l[:len(l) / 2], base, layer)
    right = multi_gpu_merge(l[len(l) / 2:], base + len(l) / 2, layer)
    owl.set_device(base)
    return left + right

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MNIST CNN')
    parser.add_argument('-n', '--num', help='number of GPUs to use', action='store', type=int, default=1)
    (args, remain) = parser.parse_known_args()
    assert(1 <= args.num)
    print 'Using %d GPU(s)' % args.num
    gpu = [owl.create_gpu_device(i) for i in range(args.num)]
    owl.set_device(gpu[0])
    model = MNISTCNNModel()
    model.init_random()
    train_network(model)