import os
import pandas as pd
import torch
from torch.utils.data import Dataset
from torchvision import transforms
from PIL import Image
import ast
from tqdm import tqdm
from typing import Callable
from albumentations.augmentations.transforms import \
        GaussNoise


class LateralSkullRadiographDataset(Dataset):
    def __init__(
        self,
        root_dir: str,
        csv_file: str,
        resize_to: tuple[int, int] = (450, 450),
        transform: transforms.Compose = transforms.Compose([
            transforms.ColorJitter(
                brightness=0.5,
                contrast=0.5,
                saturation=0.5
            ),
            GaussNoise(var_limit=0.2, mean=0, p=0.5),
        ]),
    ):
        self.data_frame = pd.read_csv(
            os.path.join(root_dir, csv_file),
        )
        self.root_dir = root_dir
        self.base_transform = transforms.Compose([
            transforms.Resize(resize_to),
            transforms.ToTensor(),
        ])
        self.resize_to = resize_to
        self.transform = transform

        print('Loading dataset into memory...')
        self.images, self.points, self.point_ids = self._load_data()
        print('Done!')

    def _parse_dimensions(self, x: str) -> tuple[int, int]:
        try:
            return eval(x)
        except Exception:
            return None

    def _load_image(self, index: int) -> torch.Tensor:
        img_name = os.path.join(
            self.root_dir,
            f"images/{self.data_frame.iloc[index]['document']}.png"
        )

        image = Image.open(img_name).convert('L')
        image = self.base_transform(image)

        return image

    @property
    def _saved_images_path(self) -> str:
        return os.path.join(self.root_dir, f'images_{self.resize_to}.pt')

    @property
    def _saved_points_path(self) -> str:
        return os.path.join(self.root_dir, 'points.pt')

    def _load_dataset(self) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        images = []
        points = []

        for index in tqdm(range(len(self.data_frame))):
            images.append(self._load_image(index))
            points.append(self._load_points(index))

        return torch.stack(images), torch.stack(points)

    def _normalize(self, images: torch.Tensor) -> torch.Tensor:
        normalize = transforms.Normalize(
            mean=images.mean(),
            std=images.std()
        )

        return normalize(images)

    def _load_data(self) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        point_ids = self._load_point_ids()

        if os.path.exists(self._saved_images_path) \
                and os.path.exists(self._saved_points_path):

            images = torch.load(self._saved_images_path)
            points = torch.load(self._saved_points_path)

            return images, points, point_ids

        images, points = self._load_dataset()

        images = self._normalize(images)

        self._save_to_pickle(images, points)

        return images, points, point_ids

    def _load_point_ids(self) -> list[str]:
        points_str = self.data_frame.iloc[0]['points']
        points_dict = ast.literal_eval(points_str)

        ids = [key for key in points_dict]

        return ids

    def _load_points(self, index: int) -> list[torch.Tensor]:
        points_str = self.data_frame.iloc[index]['points']
        points_dict = ast.literal_eval(points_str)

        points = [
            [points_dict[key]['x'], points_dict[key]['y']]
            for key in points_dict
        ]

        return torch.Tensor(points)

    def _save_to_pickle(
        self,
        images: torch.Tensor,
        points: torch.Tensor,
    ):
        torch.save(images, self._saved_images_path)
        torch.save(points, self._saved_points_path)

    def __len__(self) -> int:
        return len(self.data_frame)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        image = self.images[idx]
        points = self.points[idx]

        if self.transform is not None:
            image = self.transform(image)

        return image, points
