import torch
import torch.nn as nn
import torchvision.models as models
from torch.optim import Adam, Optimizer
from torch.optim.lr_scheduler import ReduceLROnPlateau, LRScheduler
import lightning as L

from models.losses.MaskedWingLoss import MaskedWingLoss
from models.baselines.aspp.ASPP import ASPP
from models.baselines.HeatmapBasedLandmarkDetection \
    import HeatmapBasedLandmarkDetection


class GlobalResNetBackbone(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = self._init_backbone()

        self.decoder_layers = nn.ModuleList([
            nn.Conv2d(512, 256, 1),
            nn.Conv2d(256, 128, 1),
            nn.Conv2d(128, 64, 1),
        ])

        self.upsample = nn.Upsample(
            scale_factor=2,
            mode='bilinear',
            align_corners=True
        )

    def _init_backbone(self):
        resnet = models.resnet18(pretrained=True)
        modules = list(resnet.children())[:-2]
        backbone = nn.Sequential(*modules)

        return backbone

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.backbone[0:4](x)

        layer1 = self.backbone[4](x)
        layer2 = self.backbone[5](layer1)
        layer3 = self.backbone[6](layer2)
        layer4 = self.backbone[7](layer3)

        upsample1 = self.upsample(
            self.decoder_layers[0](layer4)
        ) + layer3

        upsample2 = self.upsample(
            self.decoder_layers[1](upsample1)
        ) + layer2

        upsample3 = self.upsample(
            self.decoder_layers[2](upsample2)
        ) + layer1

        return upsample3


class GlobalDetectionModule(nn.Module, HeatmapBasedLandmarkDetection):
    def __init__(
        self,
        output_size: int = 44
    ):
        super(GlobalDetectionModule, self).__init__()

        self.output_size = output_size

        self.backbone = GlobalResNetBackbone()

        self.aspp = ASPP(64, 256, [1, 6, 12, 18])

        self.conv = nn.Conv2d(256, output_size, 1)

        self.upsample = nn.Upsample(
            scale_factor=4,
            mode='bilinear',
            align_corners=True
        )

    def forward(self, x):
        x = x.repeat(1, 3, 1, 1)
        x = self.backbone(x)
        x = self.aspp(x)
        x = self.conv(x)
        x = self.upsample(x)

        return x


class LocalResNetBackbone(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = self._init_backbone()

        self.decoder_layers = nn.ModuleList([
            nn.Conv2d(512, 256, 1),
            nn.Conv2d(256, 128, 1),
            nn.Conv2d(128, 64, 1),
        ])

        self.upsample = nn.Upsample(
            scale_factor=2,
            mode='bilinear',
            align_corners=True
        )

    def _init_backbone(self):
        resnet = models.resnet18(pretrained=True)
        modules = list(resnet.children())[:-2]
        backbone = nn.Sequential(*modules)

        return backbone

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.backbone[0:4](x.repeat(1, 3, 1, 1))

        return self.backbone[4](x)


class LocalCorrectionModule(nn.Module, HeatmapBasedLandmarkDetection):
    def __init__(self):
        super().__init__()

        self.backbone = LocalResNetBackbone()

        self.aspp = ASPP(64, 256, [1, 6, 12, 18])

        self.conv = nn.Conv2d(256, 1, 1)

        self.upsample = nn.Upsample(
            scale_factor=4,
            mode='bilinear',
            align_corners=True
        )

        self.output_size = 1

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.backbone(x)
        x = self.aspp(features)
        x = self.conv(x)
        x = self.upsample(x)

        return x


class YaoLandmarkDetection(
    L.LightningModule,
    HeatmapBasedLandmarkDetection
):
    def __init__(
        self,
        point_ids: list[str] = [],
        reduce_lr_patience: int = 25,
        model_size: str = 'tiny',
        gaussian_sigma: int = 1,
        gaussian_alpha: float = 0.1,
        resize_to: tuple[int, int] = (576, 512),
        patch_size: tuple[int, int] = (96, 96),
        num_points: int = 44,
        *args,
        **kwargs,
    ):
        super().__init__()

        self.save_hyperparameters()

        self.model_size = model_size
        self.reduce_lr_patience = reduce_lr_patience
        self.point_ids = point_ids
        self.num_points = num_points
        self.patch_size = patch_size
        self.resize_to = resize_to
        self.patch_resize_to = patch_size

        self.global_module = GlobalDetectionModule(num_points)
        self.local_module = LocalCorrectionModule()

        self.loss = nn.L1Loss(reduction='none')
        self.mm_error = MaskedWingLoss()

    def forward_with_heatmaps(
        self,
        images: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        return self.forward_batch(images, self.patch_size)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.forward_with_heatmaps(images)[-1]

    def training_step(
        self,
        batch: tuple[torch.Tensor, torch.Tensor],
        batch_idx: int
    ) -> torch.Tensor:
        loss, _, _,  _, _ = self.step(batch)

        self.log(
            'train_loss',
            loss,
            on_step=True,
            on_epoch=True,
            prog_bar=True
        )

        return loss

    def validation_step(self, batch, batch_idx):
        loss, unreduced_mm_error, _, _ = self.validation_test_step(batch)

        self.log('val_loss', loss, prog_bar=True)
        self.log('val_mm_error', unreduced_mm_error.mean(), prog_bar=True)

        return loss

    def test_step(self, batch, batch_idx):
        (
            loss,
            unreduced_mm_error,
            predictions,
            targets
        ) = self.validation_test_step(batch)

        for (id, point_id) in enumerate(self.point_ids):
            self.log(f'{point_id}_mm_error', unreduced_mm_error[id].mean())

        self.log('test_loss', loss, prog_bar=True)
        self.log('test_mm_error', unreduced_mm_error.mean(), prog_bar=True)

        self.log(
            'percent_under_1mm',
            self.mm_error.percent_under_n_mm(predictions, targets, 1)
        )
        self.log(
            'percent_under_2mm',
            self.mm_error.percent_under_n_mm(predictions, targets, 2)
        )
        self.log(
            'percent_under_3mm',
            self.mm_error.percent_under_n_mm(predictions, targets, 3)
        )
        self.log(
            'percent_under_4mm',
            self.mm_error.percent_under_n_mm(predictions, targets, 4)
        )

        return loss

    def configure_optimizers(self) -> tuple[Optimizer, LRScheduler]:
        optimizer = Adam(self.parameters(), lr=0.001)
        scheduler = ReduceLROnPlateau(
            optimizer,
            patience=self.reduce_lr_patience
        )

        return {
            'optimizer': optimizer,
            'lr_scheduler': scheduler,
            'monitor': 'val_loss'
        }
