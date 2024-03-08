import matplotlib.pyplot as plt
import torch
from lightning import Callback, Trainer, LightningModule
import os

from utils.clamp_points import clamp_points
from utils.resize_points import resize_points


class ImagePredictionLogger(Callback):
    def __init__(
        self,
        num_samples: int,
        resized_image_size: tuple[int, int],
        resized_point_reference_frame_size: tuple[int, int]
    ):
        super().__init__()
        self.num_samples = num_samples
        self.resized_image_size = resized_image_size
        self.resized_point_reference_frame_size = resized_point_reference_frame_size

    def on_validation_epoch_start(
        self,
        trainer: Trainer,
        pl_module: LightningModule
    ) -> None:
        images, targets = next(iter(trainer.datamodule.val_dataloader()))
        images = images[:self.num_samples]

        targets = resize_points(
            targets[:self.num_samples],
            self.resized_image_size,
            self.resized_point_reference_frame_size
        )

        preds = pl_module(images)

        preds = resize_points(
            preds,
            self.resized_image_size,
            self.resized_point_reference_frame_size
        )

        preds = clamp_points(preds, images).cpu().numpy()
        targets = clamp_points(targets, images).cpu().numpy()

        images = images.permute(0, 2, 3, 1).cpu().numpy()

        fig, axs = plt.subplots(
            nrows=1,
            ncols=self.num_samples,
            figsize=(60, 100)
        )

        for i, (image, target, pred) in enumerate(zip(images, targets, preds)):
            axs[i].imshow(image, cmap='gray')
            axs[i].scatter(*zip(*target), color='red', s=20)
            axs[i].scatter(*zip(*pred), color='blue', s=20)
            axs[i].axis('off')

        plt.tight_layout()

        if not os.path.exists('figures'):
            os.makedirs('figures')

        path = f'figures/figure_{self.module_name}.png'
        plt.savefig(path, bbox_inches='tight')

        image = torch.from_numpy(
            plt.imread(path)
        ).permute(2, 0, 1)

        trainer.logger.experiment.add_image(
            'predictions_vs_targets',
            image,
            global_step=1
        )

        plt.close(fig)
