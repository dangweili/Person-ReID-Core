import sys
import os
import numpy as np
import random

sys.path.append(os.getcwd())

import torch
import torch.optim as optim
import torchvision.transforms as transforms
import torch.nn.functional as F
import torch.backends.cudnn as cudnn
from torch.autograd import Variable
from torch.nn.parallel import DataParallel
import pickle
import time
import argparse

from core.dataset.Sampler import RandomIdentitySampler
from core.dataset.Dataset import ReIDDataset
from core.dataset.Dataset import ReIDTestDataset
from core.model.Res50BaseModel import Res50Model
from core.model.Res50BaseModel import Res50ExtractFeature 
from core.loss.triplet import TripletLoss
from core.utils.evaluate import reid_evaluate
from core.utils.utils import str2bool
from core.utils.utils import set_seed 
from core.utils.utils import transfer_optim_state
from core.utils.utils import time_str
from core.utils.utils import save_ckpt, load_ckpt
from core.utils.utils import load_state_dict 
from core.utils.utils import ReDirectSTD
from core.utils.utils import adjust_lr_staircase
from core.utils.utils import set_devices
from core.utils.utils import AverageMeter
from core.utils.utils import to_scalar 
from core.utils.utils import may_set_mode 
from core.utils.utils import may_mkdir 

class Config(object):
    def __init__(self):
        
        parser = argparse.ArgumentParser()
        parser.add_argument('-d', '--sys_device_ids', type=eval, default=(6,))
        parser.add_argument('--set_seed', type=str2bool, default=False)

        ## dataset parameter
        parser.add_argument('--dataset', type=str, default='market1501',
                choices=['market1501','cuhk03_detected', 'cuhk03_labeled', 'duke', 'mars', 'viper', 'viper'])
        parser.add_argument('--split', type=str, default='trainval',
                            choices=['trainval', 'train'])
        parser.add_argument('--test_split', type=str, default='test')
        parser.add_argument('--rerank', type=str2bool, default=False)
        parser.add_argument('--eval_video', type=str2bool, default=False)
        parser.add_argument('--partition_idx', type=int, default=0)
        parser.add_argument('--resize', type=eval, default=(256, 128))
        parser.add_argument('--mirror', type=str2bool, default=True)
        parser.add_argument('--batch_size', type=int, default=128)
        parser.add_argument('--workers', type=int, default=2)
        # for triplet loss
        parser.add_argument('--num_instances', type=int, default=4) # as 8 identites
        # model
        parser.add_argument('--last_conv_stride', type=int, default=2, choices=[1,2])
        parser.add_argument('--num_stripes', type=int, default=6)
        parser.add_argument('--local_conv_out_channels', type=int, default=256)
        parser.add_argument('--sgd_weight_decay', type=float, default=0.0005)
        parser.add_argument('--sgd_momentum', type=float, default=0.9)
        parser.add_argument('--new_params_lr', type=float, default=0.1)
        parser.add_argument('--finetuned_params_lr', type=float, default=0.01)
        parser.add_argument('--staircase_decay_at_epochs', type=eval,
                            default=(101, 201,))
        parser.add_argument('--staircase_decay_multiple_factor', type=float,
                            default=0.1)
        parser.add_argument('--total_epochs', type=int, default=150)
        # utils
        parser.add_argument('--resume', type=str2bool, default=False)
        parser.add_argument('--ckpt_file', type=str, default='')
        parser.add_argument('--model_weight_file', type=str, default='')
        parser.add_argument('--test_only', type=str2bool, default=False)
        parser.add_argument('--repeat_times', type=int, default=1)
        parser.add_argument('--exp_dir', type=str, default='')
        parser.add_argument('--log_to_file', type=str2bool, default=True)
        parser.add_argument('--steps_per_log', type=int, default=20)
        parser.add_argument('--epochs_per_val', type=int, default=10)
        parser.add_argument('--epochs_per_save', type=int, default=50)
        parser.add_argument('--run', type=int, default=1)
        parser.add_argument('--eval_type', type=eval, default=['sq'])
        parser.add_argument('--cuhk03_new', type=str2bool, default=True)
        args = parser.parse_args()
        

        # gpu ids
        self.sys_device_ids = args.sys_device_ids
        # random
        self.set_seed = args.set_seed
        if self.set_seed:
            self.rand_seed = 0
        else: 
            self.rand_seed = None
        # run time index
        self.run = args.run
        # Dataset #
        datasets = dict()
        datasets['market1501'] = './dataset/market1501/market1501_dataset.pkl'
        datasets['cuhk03_detected'] = './dataset/cuhk03/cuhk03_detected_dataset.pkl'
        datasets['cuhk03_labeled'] = './dataset/cuhk03/cuhk03_labeled_dataset.pkl'
        datasets['duke'] = './dataset/dukemtmcreid/dukemtmcreid_dataset.pkl'
        datasets['mars'] = './dataset/mars/mars_dataset.pkl'
        datasets['viper'] = './dataset/viper/viper_dataset.pkl'
        datasets['rap2'] = './dataset/rap2/rap2reid_dataset.pkl'
        partitions = dict()
        partitions['market1501'] = './dataset/market1501/market1501_partition.pkl'
        partitions['duke'] = './dataset/dukemtmcreid/dukemtmcreid_partition.pkl'
        partitions['mars'] = './dataset/mars/mars_partition.pkl'
        partitions['viper'] = './dataset/viper/viper_partition.pkl'
        datasets['rap2'] = './dataset/rap2/rap2reid_partition.pkl'
        self.cuhk03_new = args.cuhk03_new
        if self.cuhk03_new:
            partitions['cuhk03_detected'] = './dataset/cuhk03/cuhk03_partition_new_detected.pkl'
            partitions['cuhk03_labeled'] = './dataset/cuhk03/cuhk03_partition_new_labeled.pkl'
        else:
            partitions['cuhk03_detected'] = './dataset/cuhk03/cuhk03_partition_old.pkl'
            partitions['cuhk03_labeled'] = './dataset/cuhk03/cuhk03_partition_old.pkl'
        self.dataset_name = args.dataset
        if args.dataset not in datasets or args.dataset not in partitions:
            print("Please select the right dataset name.")
            raise ValueError
        else:
            self.dataset = datasets[args.dataset]
            self.partition = partitions[args.dataset]
        self.partition_idx = args.partition_idx
        self.split = args.split
        self.test_split = args.test_split
        self.resize = args.resize
        self.mirror = args.mirror
        self.mean = [0.485, 0.456, 0.406]
        self.std = [0.229, 0.224, 0.225]
        self.batch_size = args.batch_size
        self.workers = args.workers
        self.num_instances = args.num_instances
        # model
        self.last_conv_stride = args.last_conv_stride
        self.num_stripes = args.num_stripes
        self.local_conv_out_channels = args.local_conv_out_channels
        # optimization
        self.sgd_momentum = args.sgd_momentum
        self.sgd_weight_decay = args.sgd_weight_decay
        self.new_params_lr = args.new_params_lr
        self.finetuned_params_lr = args.finetuned_params_lr
        self.staircase_decay_at_epochs = args.staircase_decay_at_epochs
        self.staircase_decay_multiple_factor = args.staircase_decay_multiple_factor
        self.total_epochs = args.total_epochs
        # utils
        self.resume = args.resume
        self.ckpt_file = args.ckpt_file
        if self.resume:
            if self.ckpt_file == '':
                print('Please input the ckpt_file if you want to resume training')
                raise ValueError
        self.model_weight_file = args.model_weight_file
        self.test_only = args.test_only
        self.repeat_times = args.repeat_times
        self.rerank = args.rerank
        self.eval_video = args.eval_video
        self.exp_dir = args.exp_dir
        self.log_to_file = args.log_to_file
        self.steps_per_log = args.steps_per_log
        self.epochs_per_val = args.epochs_per_val
        self.epochs_per_save = args.epochs_per_save
        self.run = args.run
        
        # for evaluation
        self.cuhk03_new = args.cuhk03_new
        self.eval_type = args.eval_type
        self.test_kwargs = dict()
        self.test_kwargs['eval_type'] = self.eval_type
        self.test_kwargs['rerank'] = self.rerank
        self.test_kwargs['dist_type'] = 'euclidean'
        self.test_kwargs['eval_video'] = self.eval_video
        self.test_kwargs['feat_pool_type'] = 'average' # [average, max]
        #for cuhk03 dataset, default is new
        self.test_kwargs['cuhk03_new'] = self.cuhk03_new
        self.test_kwargs['repeat_times'] = self.repeat_times 

        if self.exp_dir == '':
            self.exp_dir = os.path.join('exp_triplet', 
                '{}'.format(self.dataset_name),
                'partition{}'.format(self.partition_idx),
                'run{}'.format(self.run))
        self.stdout_file = os.path.join(self.exp_dir, \
            'log', 'stdout_{}.txt'.format(time_str()))
        self.stderr_file = os.path.join(self.exp_dir, \
            'log', 'stderr_{}.txt'.format(time_str()))
        may_mkdir(self.stdout_file)

### main function ###
cfg = Config()

# log
if cfg.log_to_file:
    ReDirectSTD(cfg.stdout_file, 'stdout', False)
    ReDirectSTD(cfg.stderr_file, 'stderr', False)

# dump the configuration to log.
import pprint
print('-' * 60)
print('cfg.__dict__')
pprint.pprint(cfg.__dict__)
print('-' * 60)

# set the random seed
if cfg.set_seed:
    set_seed( cfg.rand_seed )
# init the gpu ids
set_devices(cfg.sys_device_ids)

# dataset 
normalize = transforms.Normalize(mean=cfg.mean, std=cfg.std)
transform = transforms.Compose([
        transforms.Resize(cfg.resize),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        normalize,])
train_set = ReIDDataset(
    dataset = cfg.dataset, 
    partition = cfg.partition,
    split = cfg.split,
    partition_idx= cfg.partition_idx,
    transform = transform)
num_classes = len(train_set.id2label.keys())
# add the sampler
train_sampler = RandomIdentitySampler(train_set, cfg.num_instances)
ids_last = (len(train_sampler)/cfg.num_instances)%(cfg.batch_size/cfg.num_instances)
if ids_last > 1:
    drop_last = False
else:
    drop_last = True
train_loader = torch.utils.data.DataLoader(
    dataset = train_set,
    batch_size = cfg.batch_size,
    num_workers = cfg.workers,
    sampler = train_sampler,
    pin_memory = True,
    drop_last = drop_last)

test_transform = transforms.Compose([
        transforms.Resize(cfg.resize),
        transforms.ToTensor(),
        normalize,])
test_set = ReIDTestDataset(
    dataset = cfg.dataset,
    partition = cfg.partition,
    split = cfg.test_split,
    partition_idx = cfg.partition_idx,
    transform = test_transform)
### ReID model ###
model = Res50Model(
    last_conv_stride = cfg.last_conv_stride,
    num_classes = num_classes)

# Wrap the model after set_devices, data parallel
# model_w = torch.nn.DataParallel(model)
model_w = model
# criterion = torch.nn.CrossEntropyLoss() # add the cuda
criterion = TripletLoss(margin=0.3).cuda() # add the cuda

# Optimizer
finetuned_params = list(model.base.parameters())
new_params = [p for n, p in model.named_parameters()
              if not n.startswith('base.')]
param_groups = [{'params': finetuned_params, 'lr': cfg.finetuned_params_lr},
                {'params': new_params, 'lr': cfg.new_params_lr}]

#optimizer = optim.SGD(
#    param_groups,
#    momentum = cfg.sgd_momentum,
#    weight_decay = cfg.sgd_weight_decay)

# using the adam optimizer
optimizer = optim.Adam(param_groups, 
    weight_decay=cfg.sgd_weight_decay)

def adjust_lr(param_groups, epoch):
    lr =  0.0003 if epoch <= 100 else \
        0.0003 * (0.001 ** ((epoch - 100) / 50.))
    for g in param_groups:
        g['lr'] = lr


# bind the model and optimizer
modules_optims = [model, optimizer]

### Resume or not ###
if cfg.resume:
    # store the model, optimizer, epoch 
    start_epoch, scores = load_ckpt(modules_optims, cfg.ckpt_file)
    start_epoch = start_epoch - 1
else:
    start_epoch = 0

model_w = torch.nn.DataParallel(model)
model_w.cuda()
transfer_optim_state(state=optimizer.state, device_id=0)

# print(the model for check
print(model

# cudnn.benchmark = True
# for evaluation
feat_func = Res50ExtractFeature(model_w)
# test only
if cfg.test_only:
    result = reid_evaluate(feat_func, test_set, **cfg.test_kwargs)
    print('-' * 60)
    print('Evaluation on %s set:' % (cfg.test_split))
    for evaluation in result.keys():
        print('%s:' % (evaluation))
        print("mAP: %.4f, Rank1: %.4f, Rank5: %.4f, Rank10: %.4f" % (result[evaluation]['mAP'], result[evaluation]['CMC'][0, 0],\
                result[evaluation]['CMC'][0, 4], result[evaluation]['CMC'][0, 9]))
    print('-' * 60)
    sys.exit(0)
     
# training
for epoch in range(start_epoch, cfg.total_epochs):
    # adjust the learning rate
    #adjust_lr_staircase(
    #    optimizer.param_groups,
    #    [cfg.finetuned_params_lr, cfg.new_params_lr],
    #    epoch + 1,
    #    cfg.staircase_decay_at_epochs,
    #    cfg.staircase_decay_multiple_factor)
    adjust_lr(optimizer.param_groups, epoch+1)
    
    may_set_mode(modules_optims, 'train')
    # recording loss
    loss_meter = AverageMeter()
    prec_meter = AverageMeter()
    dataset_L = len(train_loader)
    ep_st = time.time()

    for step, (imgs, targets) in enumerate(train_loader):
        step_st = time.time()
        imgs_var = Variable(imgs.cuda())
        targets = targets.cuda()
        
        feat = model_w(imgs_var)
        
        loss, prec = criterion(feat, targets)
    
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        ############
        # step log #
        ############
        loss_meter.update(to_scalar(loss))
        prec_meter.update(prec)
        if (step+1) % cfg.steps_per_log == 0 or (step+1)%len(train_loader) == 0:
            log = '\tStep {}/{} in Ep {}, {:.2f}s, loss{:.4f}, prec{:.4f}'.format(
                step+1, dataset_L, epoch+1, time.time()-step_st, loss_meter.val, prec_meter.val)
            print(log)

    ##############
    # epoch log  #
    ##############
    log = 'Ep{}, {:.2f}s, loss {:.4f}, prec {:.4f}'.format(
        epoch+1, time.time() - ep_st, loss_meter.avg, prec_meter.avg)
    print(log)

    # model ckpt
    if (epoch + 1) % cfg.epochs_per_save == 0:
        ckpt_file = os.path.join(cfg.exp_dir, 'model', 'ckpt_epoch%d.pth'%(epoch+1))
        save_ckpt(modules_optims, epoch+1, 0, ckpt_file)

    ##########################
    # test on validation set #
    ##########################
    if (epoch + 1) % cfg.epochs_per_val == 0:
        result = reid_evaluate(feat_func, test_set, **cfg.test_kwargs)
        print('-' * 60)
        print('Evaluation on %s set:' % (cfg.test_split))
        for evaluation in result.keys():
            print('%s:' % (evaluation))
            print("mAP: %.4f, Rank1: %.4f, Rank5: %.4f, Rank10: %.4f" % (result[evaluation]['mAP'], result[evaluation]['CMC'][0, 0],\
                result[evaluation]['CMC'][0, 4], result[evaluation]['CMC'][0, 9]))
        print('-' * 60)
