from __future__ import print_function, division
import torch
import torch.nn as nn
from torch.autograd import Variable
import utils
import numpy as np

from HeatmapHelper import HeatmapHelper
from OffsetmapHelper import OffsetmapHelper


class HeatmapOffsetmapLoss(nn.Module):
    def __init__(self, config):
        super().__init__()
        # .use_gpu, R1, R2, image_scale, batchSize, landmarkNum
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.heatmap_helper = HeatmapHelper(
            resized_image_size=config.image_scale,
        )
        self.offsetmap_helper = OffsetmapHelper(
            resized_image_size=config.image_scale, offset_map_radius=41
        )
        self.use_gpu = config.use_gpu
        self.R1 = config.R1
        self.width = config.image_scale[1]
        self.higth = config.image_scale[0]
        self.imageNum = config.batchSize
        self.landmarkNum = config.landmarkNum

        self.binaryLoss = nn.BCEWithLogitsLoss(None, True).cuda(config.use_gpu)
        self.l1Loss = torch.nn.L1Loss().cuda(config.use_gpu)

        self.offsetMapx = np.ones((self.higth * 2, self.width * 2))
        self.offsetMapy = np.ones((self.higth * 2, self.width * 2))

        self.HeatMap = np.zeros((self.higth * 2, self.width * 2))
        self.mask = np.zeros((self.higth * 2, self.width * 2))

        # ~ self.binary_class_groundTruth = Variable(torch.zeros(imageNum, landmarkNum, h, w).cuda(self.use_gpu))
        self.offsetMapX_groundTruth = Variable(
            torch.zeros(self.imageNum, self.landmarkNum, self.higth, self.width).cuda(
                self.use_gpu
            )
        )
        self.offsetMapY_groundTruth = Variable(
            torch.zeros(self.imageNum, self.landmarkNum, self.higth, self.width).cuda(
                self.use_gpu
            )
        )
        self.binary_class_groundTruth1 = Variable(
            torch.zeros(self.imageNum, self.landmarkNum, self.higth, self.width).cuda(
                self.use_gpu
            )
        )
        self.binary_class_groundTruth2 = Variable(
            torch.zeros(self.imageNum, self.landmarkNum, self.higth, self.width).cuda(
                self.use_gpu
            )
        )
        self.offsetMask = Variable(
            torch.zeros(self.imageNum, self.landmarkNum, self.higth, self.width).cuda(
                self.use_gpu
            )
        )

        rr = config.R1
        dev = 4
        referPoint = (self.higth, self.width)
        for i in range(referPoint[0] - rr, referPoint[0] + rr + 1):
            for j in range(referPoint[1] - rr, referPoint[1] + rr + 1):
                temdis = utils.Mydist(referPoint, (i, j))
                if temdis <= rr:
                    self.HeatMap[i][j] = 1
        rr = config.R2
        referPoint = (self.higth, self.width)
        for i in range(referPoint[0] - rr, referPoint[0] + rr + 1):
            for j in range(referPoint[1] - rr, referPoint[1] + rr + 1):
                temdis = utils.Mydist(referPoint, (i, j))
                if temdis <= rr:
                    self.mask[i][j] = 1

        for i in range(2 * self.higth):
            self.offsetMapx[i, :] = self.offsetMapx[i, :] * i

        for i in range(2 * self.width):
            self.offsetMapy[:, i] = self.offsetMapy[:, i] * i

        self.offsetMapx = referPoint[0] - self.offsetMapx
        self.offsetMapy = referPoint[1] - self.offsetMapy
        self.HeatMap = (
            Variable(torch.from_numpy(self.HeatMap)).cuda(self.use_gpu).float()
        )
        self.mask = Variable(torch.from_numpy(self.mask)).cuda(self.use_gpu).float()
        self.offsetMapx = (
            Variable(torch.from_numpy(self.offsetMapx)).cuda(self.use_gpu).float()
            / config.R2
        )
        self.offsetMapy = (
            Variable(torch.from_numpy(self.offsetMapy)).cuda(self.use_gpu).float()
            / config.R2
        )

        self.zeroTensor = torch.zeros(
            (self.imageNum, self.landmarkNum, self.higth, self.width)
        ).cuda(self.use_gpu)

        return

    def getOffsetMask(self, h, w, X, Y):
        for imageId in range(self.imageNum):
            for landmarkId in range(self.landmarkNum):
                self.offsetMask[imageId, landmarkId, :, :] = self.mask[
                    h - X[imageId][landmarkId] : 2 * h - X[imageId][landmarkId],
                    w - Y[imageId][landmarkId] : 2 * w - Y[imageId][landmarkId],
                ]
        return self.offsetMask

    def forward(self, featureMaps, landmarks):
        #landmarks = landmarks.to(self.device)
        #heatmaps, _ = self.heatmap_helper.create_heatmaps(
        #    landmarks * torch.tensor([self.width, self.height], device=self.device).unsqueeze(0).unsqueeze(0), 40
        #)
        #offsetmaps = self.offsetmap_helper.create_offset_maps(
        #    landmarks * torch.tensor([self.width, self.height], device=self.device).unsqueeze(0).unsqueeze(0)
        #)

        #binary_losses = self.binaryLoss(
        #    featureMaps[:, :self.landmarkNum, :, :],
        #    heatmaps
        #)

        #offset_x_losses = self.l1Loss(
        #    featureMaps[:, self.landmarkNum:self.landmarkNum * 2, :, :],
        #    offsetmaps[:, :, 0],
        #)

        #offset_y_losses = self.l1Loss(
        #    featureMaps[:, self.landmarkNum * 2:, :, :],
        #    offsetmaps[:, :, 1],
        #)

        #loss = (2 * binary_losses + offset_x_losses + offset_y_losses).mean()
        
        h, w = featureMaps.size()[2], featureMaps.size()[3]
        X = np.clip(
            np.round((landmarks[:, :, 0] * (h - 1)).numpy()).astype("int"), 0, h - 1
        )
        Y = np.clip(
            np.round((landmarks[:, :, 1] * (w - 1)).numpy()).astype("int"), 0, w - 1
        )
        binary_class_groundTruth = self.binary_class_groundTruth1

        for imageId in range(self.imageNum):
            for landmarkId in range(self.landmarkNum):
                # ~ self.binary_class_groundTruth[imageId, landmarkId, :, :] = self.HeatMap[h - X[imageId][landmarkId]: 2*h - X[imageId][landmarkId], w - Y[imageId][landmarkId]: 2*w - Y[imageId][landmarkId]]
                binary_class_groundTruth[imageId, landmarkId, :, :] = self.HeatMap[
                    h - X[imageId][landmarkId] : 2 * h - X[imageId][landmarkId],
                    w - Y[imageId][landmarkId] : 2 * w - Y[imageId][landmarkId],
                ]
                self.offsetMapX_groundTruth[imageId, landmarkId, :, :] = (
                    self.offsetMapx[
                        h - X[imageId][landmarkId] : 2 * h - X[imageId][landmarkId],
                        w - Y[imageId][landmarkId] : 2 * w - Y[imageId][landmarkId],
                    ]
                )
                self.offsetMapY_groundTruth[imageId, landmarkId, :, :] = (
                    self.offsetMapy[
                        h - X[imageId][landmarkId] : 2 * h - X[imageId][landmarkId],
                        w - Y[imageId][landmarkId] : 2 * w - Y[imageId][landmarkId],
                    ]
                )

        indexs = binary_class_groundTruth > 0
        temloss = [
            (
                [
                    2
                    * self.binaryLoss(
                        featureMaps[imageId][landmarkId],
                        binary_class_groundTruth[imageId][landmarkId],
                    ),
                    self.l1Loss(
                        featureMaps[imageId][landmarkId + self.landmarkNum * 1][
                            indexs[imageId][landmarkId]
                        ],
                        self.offsetMapX_groundTruth[imageId][landmarkId][
                            indexs[imageId][landmarkId]
                        ],
                    ),
                    self.l1Loss(
                        featureMaps[imageId][landmarkId + self.landmarkNum * 2][
                            indexs[imageId][landmarkId]
                        ],
                        self.offsetMapY_groundTruth[imageId][landmarkId][
                            indexs[imageId][landmarkId]
                        ],
                    ),
                ]
                if X[imageId][landmarkId] > 0 and Y[imageId][landmarkId] > 0
                else [0, 0, 0]
            )
            for imageId in range(self.imageNum)
            for landmarkId in range(self.landmarkNum)
        ]

        loss = (
            sum([sum(temloss[ind]) for ind in range(self.imageNum * self.landmarkNum)])
        ) / (self.imageNum * self.landmarkNum)

        return loss
