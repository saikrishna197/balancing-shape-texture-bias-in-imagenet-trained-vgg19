
# coding: utf-8

# native
import os

# modules
from utils import *
from dataset import *
from vgg19min import *
from resnet50min import *
from score import *
from trainer import *
from logger import *

# pytorch
import torch
from torch.utils.data import DataLoader

import torchvision
import torchvision.transforms as transforms


requirements = {
    torch: '1'
}

check_requirements(requirements)


config = configuration()
for k, v in sorted(vars(config).items()):
    print('{0}: {1}'.format(k, v))


IMAGE_SIZE = (config.inputSize, config.inputSize)

imagenet_normalization_values = {
    'mean': [0.485, 0.456, 0.406],
    'std': [0.229, 0.224, 0.225]
}

normalize = transforms.Normalize(**imagenet_normalization_values)
denormalize = DeNormalize(**imagenet_normalization_values)


def toImage(tensor_image):
    return toPILImage(denormalize(tensor_image))

raw_transforms = transforms.Compose([
    transforms.CenterCrop(IMAGE_SIZE),
    transforms.ToTensor()
])

train_transforms = transforms.Compose([
    transforms.RandomResizedCrop(IMAGE_SIZE[0]),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    normalize
])

test_transforms = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(IMAGE_SIZE),
    transforms.ToTensor(),
    normalize
])

def load_data(dataset_name, split):
    dataset_path = os.path.join(config.rootPath, 'datasets', dataset_name)

    istrain = split == 'train'
    transforms = train_transforms if istrain else test_transforms

    dataset = MiniImageNetDataset(dataset_path, split=split, transforms=transforms)#raw_transforms)
    loader = DataLoader(dataset, batch_size=config.batchSize, shuffle=istrain, num_workers=config.numberOfWorkers)

    print('{} dataset {} has {} datapoints in {} batches'.format(split, dataset_name, len(dataset), len(loader)))

    return dataset, loader

original_train_dataset, original_train_loader = load_data('miniimagenet', 'train')
original_val_dataset, original_val_loader = load_data('miniimagenet', 'val')

stylized_train_dataset, stylized_train_loader = load_data('stylized-miniimagenet-1.0', 'train')
stylized_val_dataset, stylized_val_loader = load_data('stylized-miniimagenet-1.0', 'val')

for dataset, loader in [
    (original_train_dataset, original_train_loader),
    (original_val_dataset, original_val_loader),
    (stylized_train_dataset, stylized_train_loader),
    (stylized_val_dataset, stylized_val_loader)
]:
    print('{} Datapoints in {} Batches'.format(len(dataset), len(loader)))

dataset_names = [
    'stylized-miniimagenet-1.0', 'stylized-miniimagenet-0.9', 'stylized-miniimagenet-0.8',
    'stylized-miniimagenet-0.7', 'stylized-miniimagenet-0.6', 'stylized-miniimagenet-0.5',
    'stylized-miniimagenet-0.4', 'stylized-miniimagenet-0.3', 'stylized-miniimagenet-0.2',
    'stylized-miniimagenet-0.1', 'stylized-miniimagenet-0.0', 'miniimagenet'
]


supported_models = {
    'vgg19_vanilla_tune_fc': create_vgg19_vanilla_tune_fc,
    'vgg19_bn_all_tune_fc': create_vgg19_bn_all_tune_fc,
    'vgg19_bn_all_tune_all': create_vgg19_bn_all_tune_all,
    'vgg19_in_single_tune_after': create_vgg19_in_single_tune_after,
    'vgg19_in_single_tune_all': create_vgg19_in_single_tune_all,
    'vgg19_in_affine_single_tune_all': create_vgg19_in_affine_single_tune_all,
    'vgg19_in_all_tune_all': create_vgg19_in_all_tune_all,
    'vgg19_in_bs_single_tune_after': create_vgg19_in_bs_single_tune_after,
    'vgg19_in_bs_single_tune_after_eval': create_vgg19_in_bs_eval,
    'vgg19_in_bs_single_tune_all': create_vgg19_in_bs_single_tune_all,
    'vgg19_in_bs_single_tune_all_eval': create_vgg19_in_bs_eval,
    'vgg19_in_bs_all_tune_all': create_vgg19_in_bs_all_tune_all,
    'vgg19_bn_single_in_tune_all': create_vgg19_bn_single_in_tune_all,
    'vgg19_vanilla_similarity_tune_all': create_vgg19_vanilla_similarity_tune_all,
    'vgg19_in_single_similarity_tune_all': create_vgg19_in_single_similarity_tune_all,
    'vgg19_bn_all_similarity_tune_fc': create_vgg19_bn_all_similarity_tune_fc,
    'vgg19_bn_all_similarity_tune_all': create_vgg19_bn_all_similarity_tune_all,
    # 'vgg19_cosine_tune_all_no_similarity': create_vgg19_cosine_tune_all
    # 'vgg19_custom_cosine_similarity_weight_0.04_tune_all_grad_clip_50_pos_loss': create_vgg19_cosine_tune_all
    'resnet50_tune_fc': create_resnet50_tune_fc
}

models = {k:v for (k,v) in supported_models.items() if k in (config.model if config.model is not None else supported_models)}

# sanity(models, original_train_loader, config.device)


# models directory
model_directory = pathJoin(config.rootPath, 'models')

if config.train:

    similarity_weight = 0.04

    # setup log directory
    log_directory = pathJoin('run_logs')
    os.makedirs(log_directory, exist_ok=True)

    for model_name in models:

        # original
        logger = create_logger(log_directory, model_name)
        logger.info('Model Name {}'.format(model_name))
        model = models[model_name]()
        run(
            model_name, model,
            model_directory,
            config.numberOfEpochs,
            logger,
            original_train_loader,
            original_val_loader, config.device,
            similarity_weight=similarity_weight if 'similarity' in model_name else None,
            load_data=load_data
        )

        # # stylized
        # model_name = 'stylized_{}'.format(model_name)
        # logger = create_logger(log_directory, model_name)
        # logger.info('Run Name {}'.format(model_name))
        # model = models[model_name]()
        # run(model_name, model, training, epochs, monitor, logger, stylized_train_loader, stylized_val_loader)

        del model
        torch.cuda.empty_cache()


# Check Performance

perf(models, model_directory, dataset_names, config.device, load_data=load_data)
