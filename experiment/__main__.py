from datetime import date
import argparse
import lightning as L
from lightning.pytorch.callbacks import ModelCheckpoint, EarlyStopping
from lightning.pytorch.loggers import TensorBoardLogger
from lightning.pytorch.profilers import PyTorchProfiler
import torch

from utils.set_seed import set_seed
from loggers.ImagePredictionLogger import ImagePredictionLogger
from dataset.LateralSkullRadiographDataModule import \
        LateralSkullRadiographDataModule
from models.CephalometricLandmarkDetector import CephalometricLandmarkDetector


def get_args() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root_dir', type=str, default='dataset')
    parser.add_argument(
        '--csv_file', type=str, default='all_images_same_points_dimensions.csv'
    )
    parser.add_argument(
        '--model_name', type=str, default='ViT', choices=['ViT', 'ConvNextV2']
    )
    parser.add_argument('--splits', type=tuple, default=(0.8, 0.1, 0.1))
    parser.add_argument('--batch_size', type=int, default=32)
    parser.add_argument('--early_stopping_patience', type=int, default=100)
    parser.add_argument('--checkpoint', type=str, default=None)
    parser.add_argument('--test_only', action=argparse.BooleanOptionalAction)
    parser.add_argument('--num_runs', type=int, default=1)

    args = parser.parse_args()

    return args


def run(args: dict, seed: int = 42) -> dict:
    set_seed(seed)

    datamodule = LateralSkullRadiographDataModule(
        root_dir=args.root_dir,
        csv_file=args.csv_file,
        splits=args.splits,
        batch_size=args.batch_size
    )

    model = CephalometricLandmarkDetector(
        model_name=args.model_name,
        point_ids=datamodule.dataset.point_ids
    )

    checkpoint_callback = ModelCheckpoint(
        dirpath='checkpoints/',
        filename='{epoch}-{val_loss:.2f}',
        monitor='val_loss',
    )

    early_stopping_callback = EarlyStopping(
        monitor='val_loss',
        patience=args.early_stopping_patience,
        mode='min',
    )

    tensorboard_logger = TensorBoardLogger(
        'logs/',
        name=model.model.__class__.__name__ + ' ' + date.today().isoformat(),
    )

    image_logger = ImagePredictionLogger(num_samples=5)

    profiler = PyTorchProfiler(dirpath=".", filename="perf_logs")

    trainer = L.Trainer(
        max_epochs=10_000,
        callbacks=[checkpoint_callback, early_stopping_callback, image_logger],
        enable_checkpointing=True,
        logger=tensorboard_logger,
        profiler=profiler,
        accelerator='gpu' if torch.cuda.is_available() else 'cpu',
        devices='auto'
    )

    if args.checkpoint:
        print(f'Loading checkpoint {args.checkpoint}...')
        model = CephalometricLandmarkDetector.load_from_checkpoint(
            args.checkpoint
        )
        print('Done!')

    if not args.test_only:
        trainer.fit(model=model, datamodule=datamodule)

        model = CephalometricLandmarkDetector.load_from_checkpoint(
            trainer.checkpoint_callback.best_model_path
        )

    return trainer.test(model=model, datamodule=datamodule)


def print_mean_std(results: list[dict]) -> None:
    tensor_data = torch.tensor([list(d.values()) for d in results])

    mean = tensor_data.mean(dim=0)
    std_dev = tensor_data.std(dim=0)

    for key, m, s in zip(results[0].keys(), mean, std_dev):
        print(f'{key} - Mean: {m.item()}, Std: {s.item()}')


if __name__ == '__main__':
    args = get_args()

    all_results = []

    for run_idx in range(args.num_runs):
        results = run(args, seed=run_idx)[0]
        all_results.append(results)

    print_mean_std(all_results)
