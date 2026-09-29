import os.path

import torch
from torch.utils.data import Dataset
from torchaudio.io import StreamReader

cuda_conf = {
    "decoder": "h264_cuvid",  # Use CUDA HW decoder
    "hw_accel": "cuda:0",  # Then keep the memory on CUDA:0
}

cpu_conf = {
    "decoder": "h264",  # CPU decoding
}


file = "../local/GH017175.mp4"

import json


def timecode_to_frames(timecode, framerate):
    return sum(
        f * int(t)
        for f, t in zip(
            (3600 * framerate, 60 * framerate, framerate, 1),
            timecode.split(":"),
            strict=False,
        )
    )


class GameVideo(Dataset):
    def __init__(self, labeled=True):
        self.dset_dir = "game_video_dataset"
        self.video_json = list()
        for path in os.listdir(os.path.join(self.dset_dir, "jsons")):
            with open(os.path.join(self.dset_dir, "jsons", path)) as game_vid:
                json_info = json.load(game_vid)
                if labeled == json_info.get("labeled", True):
                    self.video_json.append(json_info)
                else:
                    self.video_json.append(json_info)

    def build_target(self, index, fps=60):
        out = list()
        previous_frame = 0
        cut_list = [(el["start"], el["end"]) for el in self.video_json[index]["cuts"]]
        for start, end in cut_list:
            st = timecode_to_frames(start, fps)
            en = timecode_to_frames(end, fps)
            out += [0] * (st - previous_frame) + [1] * (en - st)
            previous_frame = en
        return torch.tensor(out)

    def __len__(self):
        return len(self.games)

    def __getitem__(self, idx):
        curent_video = self.video_json[idx]

        EncodedVideo.from_path(
            os.path.join(self.dset_dir, "local_games", curent_video.file)
        )
        ApplyTransformToKey(
            key="video",
            transform=Compose(
                [
                    UniformTemporalSubsample(num_frames),
                    Lambda(lambda x: x / 255.0),
                    NormalizeVideo(mean, std),
                    ShortSideScale(size=side_size),
                    CenterCropVideo(crop_size=(crop_size, crop_size)),
                ]
            ),
        )

        streamer = StreamReader(src=file)

        streamer.add_basic_audio_stream(
            frames_per_chunk=8000,
            sample_rate=8000,
        )
        streamer.add_basic_video_stream(
            frames_per_chunk=30,
            frame_rate=60,
            width=480,
            height=320,
            # format="gray",
        )

        labels = build_target(idx, fps)

        return streamer, self.build_target(idx)

    def split_labeled(self):
        labeled_indexes = list()
        unlabeled_indexes = list()
        for i, el in enumerate(self):
            if self.video_json[i].get("labeled", False) in [True, "reference"]:
                labeled_indexes.append(i)
            else:
                unlabeled_indexes.append(i)
        return labeled_indexes, unlabeled_indexes
