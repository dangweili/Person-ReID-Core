import torch.utils.data as data
import os
from PIL import Image
import numpy as np
import pickle
import copy

class ReIDDataset(data.Dataset):
    """
    person re-identification dataset interface
    for multi-classification model, split should be 'train' or 'trainval'
    """
    def __init__(
        self, 
        dataset,
        partition,
        split='train',
        partition_idx=0,
        transform=None,
        target_transform=None,
        **kwargs):
        if os.path.exists( dataset ):
            self.dataset = pickle.load(open(dataset, 'rb'))
        else:
            raise ValueError
        if os.path.exists( partition ):
            self.partition = pickle.load(open(partition, 'rb'))
        else:
            raise ValueError
        if split not in self.partition:
            print(split + 'does not exist in dataset.')
            raise ValueError
        
        if partition_idx > len(self.partition[split])-1:
            print('partition_idx is out of range in partition.')
            raise ValueError
        else:
            self.train_ids = self.partition[split][partition_idx]
            self.id2label = dict()
            for i in range(len(self.train_ids)):
                self.id2label[self.train_ids[i]] = i
        self.transform = transform
        self.target_transform = target_transform
        self.create_image_label_list()

    
    def create_image_label_list(self):
        """
        Generate the imagename and label lists
        """
        self.root_path = self.dataset['root']
        self.image = []
        self.label = []
        self.camera = []
        for idx, pid in enumerate(self.dataset['pid']):
            if pid in self.id2label:
                self.image.append( self.dataset['image'][idx] )
                self.label.append( self.id2label[pid] )
                self.camera.append( self.dataset['cam'][idx] )
        
    def __getitem__(self, index):
        """
        Args:
            index (int): Index
        Returns:
            tuple: (image, target) where target is the index of the target class
        """
        imgname, target = self.image[index], int(self.label[index])
        # load image and labels
        imgname = os.path.join(self.dataset['root'], imgname)
        img = Image.open(imgname)
        if self.transform is not None:
            img = self.transform( img )
        
        if self.target_transform is not None:
            target = self.target_transform(target)

        return img, target

    # useless for personal batch sampler
    def __len__(self):
        return len(self.image)

class ReIDTestDataset(data.Dataset):
    """
    person re-identification test set, including val.
    """
    def __init__(
        self, 
        dataset,
        partition,
        split='val',
        partition_idx=0,
        transform=None,
        target_transform=None,
        **kwargs):
        if os.path.exists( dataset ):
            self.dataset = pickle.load(open(dataset, 'rb'))
        else:
            raise ValueError
        if os.path.exists( partition ):
            self.partition = pickle.load(open(partition, 'rb'))
        else:
            raise ValueError
        if split not in self.partition:
            print(split + 'does not exist in dataset.')
            raise ValueError
        
        if partition_idx > len(self.partition[split])-1:
            print('partition_idx is out of range in partition.')
            raise ValueError
        else:
            self.test_ids = self.partition[split][partition_idx]
        self.partition_idx = partition_idx
        self.split = split
        self.transform = transform
        self.target_transform = target_transform
        self.create_image_list_by_pids()
        
    
    # discuss about the list
    def create_image_list_by_pids(self):
        """
            create image list using self.dataset[split][partition_idx]
        """
        self.image = []
        self.pid = []
        self.cam = []
        self.seq = []
        self.frame = []
        self.record = []
        for index, pid in enumerate(self.dataset['pid']):
            if pid in self.test_ids:
                self.image.append(self.dataset['image'][index])
                self.pid.append(self.dataset['pid'][index])
                self.cam.append(self.dataset['cam'][index])
                self.seq.append(self.dataset['seq'][index])
                self.frame.append(self.dataset['frame'][index])
                self.record.append(self.dataset['record'][index])
     
    def create_image_list_by_fixed_query(self):
        """
            create image list using fixed query 
        """
        self.image = copy.deepcopy( self.dataset['image_q'] )
        self.pid = copy.deepcopy( self.dataset['pid_q'] ) 
        self.cam = copy.deepcopy( self.dataset['cam_q'] ) 
        self.seq = copy.deepcopy( self.dataset['seq_q'] )
        self.frame = copy.deepcopy( self.dataset['frame_q'] )
        self.record = copy.deepcopy( self.dataset['record_q'] )
    
    def create_image_list_by_fixed_gallery(self):
        """
            create image list using fixed gallery 
        """
        self.image = copy.deepcopy( self.dataset['image_g'] )
        self.pid = copy.deepcopy( self.dataset['pid_g'] ) 
        self.cam = copy.deepcopy( self.dataset['cam_g'] ) 
        self.seq = copy.deepcopy( self.dataset['seq_g'] )
        self.frame = copy.deepcopy( self.dataset['frame_g'] )
        self.record = copy.deepcopy( self.dataset['record_g'] )
    
    def create_image_list_by_fixed_groundtruth(self):
        """
            create image list using fixed groundtruth 
        """
        self.image = copy.deepcopy( self.dataset['image_gt'] )
        self.pid = copy.deepcopy( self.dataset['pid_gt'] ) 
        self.cam = copy.deepcopy( self.dataset['cam_gt'] ) 
        self.seq = copy.deepcopy( self.dataset['seq_gt'] )
        self.frame = copy.deepcopy( self.dataset['frame_gt'] )
        self.record = copy.deepcopy( self.dataset['record_gt'] )
    
    def __len__(self):
        return len(self.image)

    def __getitem__(self, index):
        """
        Args:
            index (int): Index
        Returns:
            images
        """
        imgname = self.image[index]
        imgname = os.path.join(self.dataset['root'], imgname)
        img = Image.open(imgname)
        if self.transform is not None:
            img = self.transform( img )
        return img

