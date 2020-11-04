"""Object Detection Trainer."""
from trainer.trainer import Trainer
import numpy as np
import torch
from torchvision.utils import make_grid
from base import BaseTrainer
from utils import inf_loop, MetricTracker


class ObjectDetectionTrainer(BaseTrainer):
    def __init__(
        self,
        model,
        criterion,
        metric_ftns,
        optimizer,
        config,
        data_loader,
        valid_data_loader=None,
        lr_scheduler=None,
        len_epoch=None,
    ):
        super().__init__(model, criterion, metric_ftns, optimizer, config, data_loader)
        self.config = config
        self.data_loader = data_loader
        if len_epoch is None:
            # Do epoch-based training.
            self.len_epoch = len(self.data_loader)
        else:
            # Do iteration-based training.
            self.data_loader = inf_loop(data_loader)
            self.len_epoch = len_epoch

        self.valid_data_loader = valid_data_loader
        self.do_validation = self.valid_data_loader is not None
        self.lr_scheduler = lr_scheduler
        self.log_step = int(np.sqrt(data_loader.batch_size))

        self.train_metrics = MetricTracker(
            "loss", *[m.__name__ for m in self.metric_ftns], writer=self.writer
        )
        self.valid_metrics = MetricTracker(
            "loss", *[m.__name__ for m in self.metric_ftns], writer=self.writer
        )

        # Init criterion.
        self.criterion = criterion(priors_cxcy=self.model.priors_cxcy).to(self.device)

    def _train_epoch(self, epoch):
        """
        Training logic for an epocha.

        Args:
          epoch: Integer, current training epoch.

        Returns:
          A log that container average loss and metric in this epoch.
        """
        self.model.train()
        self.train_metrics.reset()

        for batch_idx, (images, boxes, labels, _) in enumerate(self.data_loader):
            images = images.to(self.device)
            boxes = [b.to(self.device) for b in boxes]
            labels = [l.to(self.device) for l in labels]

            self.optimizer.zero_grad()
            pred_locs, pred_scores = self.model(images)
            loss = self.criterion(pred_locs, pred_scores, boxes, labels)
            loss.backward()
            self.optimizer.step()

            self.writer.set_step((epoch - 1) * self.len_epoch + batch_idx)
            self.train_metrics.update("loss", loss.item())

            ## with torch.no_grad:
            ##   det_boxes_batch, det_lables_batch, det_scores_batch = self.model.detect_objects(
            ##     pred_locs, pred_scores, min_score=0.01, max_overlap=0.45, top_k=200
            ##   )

            ##

            ## for met in self.metric_ftns:
            ##   self.train_metrics.update(met.__name__, met())
            if batch_idx % self.log_step == 0:
                self.logger.debug(
                    "Train Epoch: {} {} Loss: {:.6f}".format(
                        epoch, self._progress(batch_idx), loss.item()
                    )
                )
                self.writer.add_image(
                    "input", make_grid(images.cpu(), nrow=8, normalize=True)
                )

            if batch_idx == self.len_epoch:
                break

        log = self.train_metrics.result()

        if self.do_validation:
            val_log = self._valid_epoch(epoch)
            log.update(**{"val_" + k: v for k, v in val_log.items()})

        if self.lr_scheduler is not None:
            self.lr_scheduler.step()
        return log

    def _valid_epoch(self, epoch):
        """
        Validate after training an epoch.

        Args:
          epoch: Integer, current training epoch.

        Returns:
          A log that contains information about validation.
        """

        self.model.eval()
        self.valid_metrics.reset()

        det_boxes = []
        det_labels = []
        det_scores = []
        true_boxes = []
        true_labels = []
        true_difficulties = []

        with torch.no_grad():
            for batch_idx, (images, boxes, labels, difficulties) in enumerate(
                self.valid_data_loader
            ):
                images = images.to(self.device)

                pred_locs, pred_scores = self.model(images)
                loss = self.criterion(pred_locs, pred_scores, boxes, labels)

                self.writer.set_step(
                    (epoch - 1) * len(self.valid_data_loader) + batch_idx, "valid"
                )
                self.valid_metrics.update("loss", loss.item())

                ## det_boxes_batch, det_labels

                for met in self.metric_ftns:
                    self.valid_metrics.update(met.__name__, met())

    def _progress(self, batch_idx):
        base = "[{}/{} ({:.0f}%)]"
        if hasattr(self.data_loader, "n_samples"):
            current = batch_idx * self.data_loader.batch_size
            total = self.data_loader.n_samples
        else:
            current = batch_idx
            total = self.len_epoch
        return base.format(current, total, 100.0 * current / total)
