import os
import torch
import numpy as np
from score import *
from utils import *
from torchvision.utils import save_image

DEBUG = False

def calculate_similarity_loss(similarity, kernel_sizes=[64., 128., 256., 512., 512.]):
    number_of_kernels = torch.tensor(kernel_sizes)
    style_weights = torch.tensor([1e3/n**2 for n in number_of_kernels])
    weighted_similarity = style_weights * similarity
    return weighted_similarity.mean() + (number_of_kernels * style_weights).sum()


def sanity(model_list, loader, device):
    for model_type in model_list:
        print(model_type)
        model = model_list[model_type]()
        model.train()
        for batch in loader:
            index_image = loader.dataset.INDEX_IMAGE
            model(batch[index_image].to(device))
            break
        del model
        torch.cuda.empty_cache()


def validate(model, dataloader, criterion, logger, device, similarity_weight=None):
    logger.debug('Validation Start')
    model.eval()
    
    total_top1, total_top5, total_, top1_score, top5_score = 0, 0, 0, 0, 0
    loss = []
    if similarity_weight is not None:
        classification_loss = []
        similarity_loss = []

    for batch_index, batch in enumerate(dataloader):
        if similarity_weight is not None:
            output, batch_similarity = model(batch[dataloader.dataset.INDEX_IMAGE].to(device))
        else:
            output = model(batch[dataloader.dataset.INDEX_IMAGE].to(device))
        target = batch[dataloader.dataset.INDEX_TARGET].to(device)

        _, predicted_class = output.topk(5, 1, True, True)
        top1, top5, total = score(predicted_class, target)

        total_top1 += top1
        total_top5 += top5
        total_ += total

        # loss
        if similarity_weight is not None:
            batch_classification_loss = criterion(output, target)
            batch_similarity_loss = calculate_similarity_loss(batch_similarity)
        
            batch_loss = batch_classification_loss + (similarity_weight * batch_similarity_loss)
        else:
            batch_loss = criterion(output, target)

        loss.append(batch_loss.item())
        mean_loss = np.mean(loss)

        if similarity_weight is not None:
            classification_loss.append(batch_classification_loss.item())
            similarity_loss.append(batch_similarity_loss.item())
            mean_classification_loss = np.mean(classification_loss)
            mean_similarity_loss = np.mean(similarity_loss)

        top1_score = score_value(total_top1, total_)
        top5_score = score_value(total_top5, total_)
        if (batch_index + 1) % 10 == 0:
            if similarity_weight is not None:
                logger.debug('Validation Batch {0}/{1}: Top1 Accuracy {2:.4f} Top5 Accuracy {3:.4f} Loss {4:.4f} Classification Loss {5:.4f} Similarity Loss {6:.4f} Similarity Weight {7:.2f}'.format(batch_index + 1, len(dataloader), top1_score, top5_score, mean_loss, mean_classification_loss, mean_similarity_loss, similarity_weight))
            else:
                logger.debug('Validation Batch {0}/{1}: Top1 Accuracy {2:.4f} Top5 Accuracy {3:.4f} Loss {4:.4f}'.format(batch_index + 1, len(dataloader), top1_score, top5_score, mean_loss))
            if DEBUG:
                break

    logger.debug('Validation End')
    return top1_score, top5_score, mean_loss


def train(model, dataloader, criterion, optimizer, logger, device, similarity_weight=None, grad_clip_norm_value=50):
    logger.debug('Training Start')
    model.train()

    total_top1, total_top5, total_, top1_score, top5_score = 0, 0, 0, 0, 0
    loss = []
    if similarity_weight is not None:
        classification_loss = []
        similarity_loss = []

    for batch_index, batch in enumerate(dataloader):
        optimizer.zero_grad()
        if similarity_weight is not None:
            output, batch_similarity = model(batch[dataloader.dataset.INDEX_IMAGE].to(device))
        else:
            output = model(batch[dataloader.dataset.INDEX_IMAGE].to(device))
        target = batch[dataloader.dataset.INDEX_TARGET].to(device)

        # accuracy
        _, predicted_class = output.topk(5, 1, True, True)
        top1, top5, total = score(predicted_class, target)

        total_top1 += top1
        total_top5 += top5
        total_ += total

        # loss
        if similarity_weight is not None:
            batch_similarity_loss = calculate_similarity_loss(batch_similarity)
            batch_classification_loss = criterion(output, target)

            batch_loss = batch_classification_loss + (similarity_weight * batch_similarity_loss)
        else:
            batch_loss = criterion(output, target)

        loss.append(batch_loss.item())

        # backprop
        batch_loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm_value)
        optimizer.step()
        
        # use mean metrics
        mean_loss = np.mean(loss)

        if similarity_weight is not None:
            classification_loss.append(batch_classification_loss.item())
            similarity_loss.append(batch_similarity_loss.item())
            mean_classification_loss = np.mean(classification_loss)
            mean_similarity_loss = np.mean(similarity_loss)

        top1_score = score_value(total_top1, total_)
        top5_score = score_value(total_top5, total_)
            
        if (batch_index + 1) % 10 == 0:
            if similarity_weight is not None:
                logger.debug('Training Batch {0}/{1}: Top1 Accuracy {2:.4f} Top5 Accuracy {3:.4f} Loss {4:.4f} Classification Loss {5:.4f} Similarity Loss {6:.4f} Similarity Weight {7:.2f}'.format(batch_index + 1, len(dataloader), top1_score, top5_score, mean_loss, mean_classification_loss, mean_similarity_loss, similarity_weight))
            else:
                logger.debug('Training Batch {0}/{1}: Top1 Accuracy {2:.4f} Top5 Accuracy {3:.4f} Loss {4:.4f}'.format(batch_index + 1, len(dataloader), top1_score, top5_score, mean_loss))
            if DEBUG:
                break

    logger.debug('Training End')
    return top1_score, top5_score, mean_loss


def validate_autoencoder(model, dataloader, criterion, logger, device, filename, habits_lambda=0.2):
    logger.debug('Validation Start')
    model.eval()

    loss = []

    kl_init = 0.01 * len(dataloader)
    kl_weight = 0.0
    kl_max = 1.0
    kl_step = (kl_max - kl_weight) / (len(dataloader) // 2)

    logger.debug('KL: INIT: {} WEIGHT: {} MAX: {} STEP: {}'.format(kl_init, kl_weight, kl_max, kl_step))

    for batch_index, batch in enumerate(dataloader):
        output, mu, logvar = model(batch[dataloader.dataset.INDEX_IMAGE].to(device), classify=False)
        target = batch[dataloader.dataset.INDEX_TARGET_IMAGE].to(device)

        # loss
        mse, kl = criterion(output, target, mu, logvar)
        clamp_kl = torch.clamp(kl.mean(), min=habits_lambda).squeeze()
        effective_kl = clamp_kl * kl_weight
        batch_loss = mse + effective_kl
        logger.debug('BATCH LOSS: {} MSE: {} KL-EFFECTIVE: {} KL-CLAMPED: {} KL: {} KL-WEIGHT: {}'.format(
            batch_loss.item(), mse.item(), effective_kl.item(), clamp_kl.item(), kl.item(), kl_weight))

        if batch_index > kl_init and kl_weight < kl_max:
            kl_weight += kl_step

        loss.append(batch_loss.item() / target.size(0))
        mean_loss = np.mean(loss)

        if batch_index == 0:
            n = min(target.size(0), 8)
            comparison = torch.cat([target[:n], output.view(target.size(0), target.size(1), target.size(2), target.size(3))[:n]])
            save_image(comparison.cpu(), filename, nrow=n, normalize=True)

        if (batch_index + 1) % 10 == 0:
            logger.debug('Validation Batch {}/{}: Loss {:.4f}'.format(batch_index + 1, len(dataloader), mean_loss))
            if DEBUG:
                break

    logger.debug('Validation End')
    return mean_loss


def train_autoencoder(model, dataloader, criterion, optimizer, logger, device, grad_clip_norm_value=50, habits_lambda=0.2):
    logger.debug('Training Start')
    model.train()

    loss = []

    kl_init = 0.01 * len(dataloader)
    kl_weight = 0.0
    kl_max = 1.0
    kl_step = (kl_max - kl_weight) / (len(dataloader) // 2)

    logger.debug('KL: INIT: {} WEIGHT: {} MAX: {} STEP: {}'.format(kl_init, kl_weight, kl_max, kl_step))

    for batch_index, batch in enumerate(dataloader):
        optimizer.zero_grad()
        output, mu, logvar = model(batch[dataloader.dataset.INDEX_IMAGE].to(device), classify=False)
        target = batch[dataloader.dataset.INDEX_TARGET_IMAGE].to(device)

        # loss
        mse, kl = criterion(output, target, mu, logvar)
        clamp_kl = torch.clamp(kl.mean(), min=habits_lambda).squeeze()
        effective_kl = clamp_kl * kl_weight
        batch_loss = mse + effective_kl
        logger.debug('BATCH LOSS: {} MSE: {} KL-EFFECTIVE: {} KL-CLAMPED: {} KL: {} KL-WEIGHT: {}'.format(
            batch_loss.item(), mse.item(), effective_kl.item(), clamp_kl.item(), kl.item(), kl_weight))

        if batch_index > kl_init and kl_weight < kl_max:
            kl_weight += kl_step

        loss.append(batch_loss.item() / target.size(0))

        # backprop
        batch_loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm_value)
        optimizer.step()
        
        # use mean metrics
        mean_loss = np.mean(loss)
            
        if (batch_index + 1) % 10 == 0:
            logger.debug('Training Batch {}/{}: Loss {:.4f}'.format(batch_index + 1, len(dataloader), mean_loss))
            if DEBUG:
                break

    logger.debug('Training End')
    return mean_loss


def run(model_name, model, model_directory, number_of_epochs, learning_rate, logger, train_loader, val_loader, device, similarity_weight=None, dataset_names=['miniimagenet', 'stylized-miniimagenet-1.0'], load_data=None):
    logger.info('Epochs {}'.format(number_of_epochs))
    logger.info('Batch Size {}'.format(train_loader.batch_size))
    logger.info('Number of Workers {}'.format(train_loader.num_workers))
    logger.info('Optimizer {}'.format('SGD w/ Momentum'))
    logger.info('Learning Rate {}'.format(learning_rate))
    logger.info('Similarity Weight {}'.format(similarity_weight))
    logger.info('Device {}'.format(device))

    criterion = torch.nn.CrossEntropyLoss()
    parameters = model.parameters()
    if 'autoencoder' in model_name:
        parameters = model.classifier.parameters()
    optimizer = torch.optim.SGD(parameters, lr=learning_rate, momentum=0.9)
    
    lr_scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, factor=0.2, patience=5, min_lr=1e-5, verbose=True)
    
    best_validation_accuracy = -1.0

    for epoch in range(1, number_of_epochs + 1):
        train_top1_accuracy, train_top5_accuracy, train_loss = train(model, train_loader, criterion, optimizer, logger, device, similarity_weight)
        validation_top1_accuracy, validation_top5_accuracy, validation_loss = validate(model, val_loader, criterion, logger, device, similarity_weight)
        logger.info('Epoch {0}: Train: Loss: {1:.4f} Top1 Accuracy: {2:.4f} Top5 Accuracy: {3:.4f} Validation: Loss: {4:.4f} Top1 Accuracy: {5:.4f} Top5 Accuracy: {6:.4f}'.format(epoch, train_loss, train_top1_accuracy, train_top5_accuracy, validation_loss, validation_top1_accuracy, validation_top5_accuracy))

        lr_scheduler.step(validation_loss)

        if validation_top5_accuracy > best_validation_accuracy:
            logger.debug('Improved Validation Score, saving new weights')
            os.makedirs(model_directory, exist_ok=True)
            checkpoint = {
                'epoch': epoch,
                'train_top1_accuracy': train_top1_accuracy,
                'train_top5_accuracy': train_top5_accuracy,
                'train_loss': train_loss,
                'validation_top1_accuracy': validation_top1_accuracy,
                'validation_top5_accuracy': validation_top5_accuracy,
                'validation_loss': validation_loss,
                'weights': model.state_dict(),
                'optimizer_weights': optimizer.state_dict()
            }
            torch.save(checkpoint, pathJoin(model_directory, '{}.ckpt'.format(model_name)))
            best_validation_accuracy = validation_top5_accuracy

    logger.info('Epoch {}'.format(checkpoint['epoch']))

    evaluate_model(model_name, model, load_data, dataset_names, logger.info, similarity_weight is not None, device)
    logger.info('Train: Loss: {:.4f} Top1 Accuracy: {:.4f} Top5 Accuracy: {:.4f}'.format(checkpoint['train_loss'], checkpoint['train_top1_accuracy'], checkpoint['train_top5_accuracy']))
    logger.info('Validation: Loss: {:.4f} Top1 Accuracy: {:.4f} Top5 Accuracy: {:.4f}'.format(checkpoint['validation_loss'], checkpoint['validation_top1_accuracy'], checkpoint['validation_top5_accuracy']))


class vaeLoss(torch.nn.Module):
    def __init__(self):
        super(vaeLoss, self).__init__()
        self.mse_loss = torch.nn.MSELoss(reduction='mean')

    def forward(self, x_recon, x, mu, logvar):
        loss_MSE = self.mse_loss(x_recon, x)
        loss_KLD = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())

        return loss_MSE, loss_KLD


def run_autoencoder(
        model_name, model, model_directory,
        number_of_epochs, autoencoder_learning_rate, classifier_learning_rate,
        logger, pair_train_loader, pair_val_loader, train_loader, val_loader,
        device, dataset_names=['miniimagenet', 'stylized-miniimagenet-1.0'],
        load_data=None, should_train_autoencoder=True
    ):
    if should_train_autoencoder:
        logger.info('Epochs {}'.format(number_of_epochs))
        logger.info('Batch Size {}'.format(pair_train_loader.batch_size))
        logger.info('Number of Workers {}'.format(pair_train_loader.num_workers))
        logger.info('Optimizer {}'.format('SGD w/ Momentum'))
        logger.info('Autoencoder Learning Rate {}'.format(autoencoder_learning_rate))
        logger.info('Device {}'.format(device))

        criterion = vaeLoss()
        autoencoder_parameters = list(model.encoder.parameters()) + list(model.decoder.parameters())
        optimizer = torch.optim.Adam(autoencoder_parameters, lr=autoencoder_learning_rate)
        
        lr_scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, factor=0.2, patience=5, min_lr=1e-5, verbose=True)
        
        best_validation_accuracy = -1.0

        for epoch in range(1, number_of_epochs + 1):
            model.set_mode('train-autoencoder')
            train_loss = train_autoencoder(model, pair_train_loader, criterion, optimizer, logger, device)
            model.set_mode('eval')
            images_directory = pathJoin('vae-images')
            os.makedirs(images_directory, exist_ok=True)
            images_filename = pathJoin(images_directory, '{}_epoch_{}.png'.format(model_name, epoch))
            validation_loss = validate_autoencoder(model, pair_val_loader, criterion, logger, device, images_filename)
            with torch.no_grad():
                z = torch.randn(64, model.z_size).to(device)
                x = model.latent_to_decoder(z)
                x = x.view(64, 512, 7, 7)
                sample = model.decode(x).cpu()
                sample_filename = pathJoin(images_directory, '{}_epoch_{}_samples.png'.format(model_name, epoch))
                save_image(sample.view(64, 3, 224, 224), sample_filename, normalize=True)
            logger.info('Epoch {0}: Train: Loss: {1:.4f} Validation: Loss: {2:.4f}'.format(epoch, train_loss, validation_loss))

            lr_scheduler.step(validation_loss)

            logger.debug('Saving new weights')
            os.makedirs(model_directory, exist_ok=True)
            checkpoint = {
                'epoch': epoch,
                'train_loss': train_loss,
                'validation_loss': validation_loss,
                'weights': model.state_dict(),
                'optimizer_weights': optimizer.state_dict()
            }
            torch.save(checkpoint, pathJoin(model_directory, '{}.ckpt'.format(model_name)))

        logger.info('Epoch {}'.format(checkpoint['epoch']))

    # train classifier
    model.set_mode('train-classifier')
    run(model_name, model, model_directory, number_of_epochs, classifier_learning_rate, logger, train_loader, val_loader, device, dataset_names=dataset_names, load_data=load_data)

    if should_train_autoencoder:
        logger.info('Train: Loss: {:.4f}'.format(checkpoint['train_loss']))
        logger.info('Validation: Loss: {:.4f}'.format(checkpoint['validation_loss']))


def perf(model_list, model_directory, dataset_names, device, load_data=None, only_exists=None):
    for model_name in model_list:
        print(model_name)
        model = model_list[model_name]()

        checkpoint_path = pathJoin(model_directory, '{}.ckpt'.format(model_name))
        print(checkpoint_path)
        
        if os.path.isfile(checkpoint_path):
            checkpoint = torch.load(checkpoint_path, map_location=device)

            epoch = checkpoint['epoch']
            train_top1_accuracy = checkpoint['train_top1_accuracy']
            train_top5_accuracy = checkpoint['train_top5_accuracy']
            train_loss = checkpoint['train_loss']
            validation_top1_accuracy = checkpoint['validation_top1_accuracy']
            validation_top5_accuracy = checkpoint['validation_top5_accuracy']
            validation_loss = checkpoint['validation_loss']
            model.load_state_dict(checkpoint['weights'])

            model.eval()

            print('Epoch: {} Validation: Loss: {:.4f} Top1 Accuracy: {:.4f} Top5 Accuracy: {:.4f} Train: Loss: {:.4f} Top1 Accuracy: {:.4f} Top5 Accuracy: {:.4f}'.format(epoch, validation_loss, validation_top1_accuracy, validation_top5_accuracy, train_loss, train_top1_accuracy, train_top5_accuracy))

            if not only_exists:
                evaluate_model(model_name, model, load_data, dataset_names, print, 'similarity' in model_name, device)
        else:
            print('Checkpoint not available for model {}'.format(model_name))
        del model
        torch.cuda.empty_cache()

