import argparse
import torch
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, BoundaryNorm
import numpy as np
import os
from pathlib import Path
import subprocess
import scipy.fft as sfft
from dataclasses import dataclass

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', required=True, type=str,
                        help='Path to directory with model and sim output.pt files')
    return parser.parse_args()

@dataclass
class BoilingData:
    velx: torch.Tensor
    vely: torch.Tensor

def load_vel_data(vel_path):
    pred = BoilingData(
            torch.load(f'{vel_path}/velx_output.pt').numpy(),
            torch.load(f'{vel_path}/vely_output.pt').numpy())
    label = BoilingData(
            torch.load(f'{vel_path}/velx_label.pt').numpy(),
            torch.load(f'{vel_path}/vely_label.pt').numpy())
    return pred, label

def main():
    args = parse_args()
    
    job_id = '31249692'
    pred, label = load_vel_data(f'test_im/vel/{job_id}')
    
    plt_vel(pred, label, args.path, 'model')

    subprocess.call(
            f'ffmpeg -y -framerate 25 -pattern_type glob -i "{args.path}/*.png" veltest.mp4',
            shell=True)

def temp_cmap():
    temp_ranges = [0.0, 0.02, 0.04, 0.06, 0.08, 0.1, 0.134, 0.167,
                    0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    color_codes = ['#0000FF', '#0443FF', '#0E7AFF', '#16B4FF', '#1FF1FF', '#21FFD3',
                   '#22FF9B', '#22FF67', '#22FF15', '#29FF06', '#45FF07', '#6DFF08',
                   '#9EFF09', '#D4FF0A', '#FEF30A', '#FEB709', '#FD7D08', '#FC4908',
                   '#FC1407', '#FB0007']
    colors = list(zip(temp_ranges, color_codes))
    cmap = LinearSegmentedColormap.from_list('temperature_colormap', colors)
    return cmap

def fft(x):
    x_fft = sfft.fft2(x)
    x_shift = np.abs(sfft.fftshift(x_fft))
    return x_shift

def mag(velx, vely):
    return np.sqrt(velx**2 + vely**2)

def plt_vel(pred, label, path, model_name):
    plt.rc("font", family="serif", size=16, weight="bold")
    plt.rc("axes", labelweight="bold")

    label_mag = mag(label.velx, label.vely)
    pred_mag = mag(pred.velx, pred.vely)
    mag_vmax = abs(pred_mag[:50]).max()
    print(label_mag.max(), pred_mag.max())

    frames = min(pred.velx.shape[0], 100)
    for i in range(frames):
        i_str = str(i).zfill(3)
        f, ax = plt.subplots(1, 2, layout='constrained')
        
        x_vmax, x_vmin = label.velx.max(), label.velx.min()
        y_vmax, y_vmin = label.vely.max(), label.vely.min()

        #cm_object = ax[0, 0].imshow(np.flipud(label.temp[i]), vmin=0, vmax=1, cmap=temp_cmap())
        #ax[1, 0].imshow(np.flipud(label.velx[i]), vmin=x_vmin, vmax=x_vmax, cmap='jet')
        #ax[2, 0].imshow(np.flipud(label.vely[i]), vmin=y_vmin, vmax=y_vmax, cmap='jet')
        ax[0].imshow(np.flipud(label_mag[i]), vmin=0, vmax=mag_vmax, cmap='jet')

        #ax[0, 1].imshow(np.flipud(np.nan_to_num(pred.temp[i])), vmin=0, vmax=1, cmap=temp_cmap())
        #ax[1, 1].imshow(np.flipud(pred.velx[i]), vmin=x_vmin, vmax=x_vmax, cmap='jet')
        #ax[2, 1].imshow(np.flipud(pred.vely[i]), vmin=y_vmin, vmax=x_vmax, cmap='jet')
        ax[1].imshow(np.flipud(pred_mag[i]), vmin=0, vmax=mag_vmax, cmap='jet')
        ax[0].set_title(f'Label Magnitude\n', fontdict={'fontsize': 14, 'fontweight': 'bold'})
        ax[1].set_title(f'Predicted Magnitude\n', fontdict={'fontsize': 14, 'fontweight': 'bold'})
        ax[0].axis('off')
        ax[1].axis('off')
        # ax[0, 1].axis('off')
        # ax[1, 1].axis('off')

        #ax[0, 2].imshow(np.flipud(fft(label.temp[i])))
        #ax[1, 2].imshow(np.flipud(fft(label.velx[i])))
        #ax[2, 2].imshow(np.flipud(fft(label.vely[i])))
        #ax[3, 2].imshow(np.flipud(fft(label_mag)))

        #ax[0, 3].imshow(np.flipud(fft(pred.temp[i])))
        #ax[1, 3].imshow(np.flipud(fft(pred.velx[i])))
        #ax[2, 3].imshow(np.flipud(fft(pred.vely[i])))
        #ax[3, 3].imshow(np.flipud(fft(pred_mag)))

        im_path = Path(path)
        im_path.mkdir(parents=True, exist_ok=True)
        plt.savefig(f'{str(im_path)}/{i_str}.png',
                    dpi=200,
                    bbox_inches='tight',
                    transparent=True)
        plt.close()


# def plt_vel(pred, label, path, model_name):
#     plt.rc("font", family="serif", size=16, weight="bold")
#     plt.rc("axes", labelweight="bold")

#     label_mag = mag(label.velx, label.vely)
#     pred_mag = mag(pred.velx, pred.vely)
#     mag_vmax = max(abs(label_mag).max(), abs(pred_mag).max())

#     frames = min(pred.velx.shape[0], 100)
#     for i in range(frames):
#         i_str = str(i).zfill(3)
#         f, ax = plt.subplots(1, 2, layout='constrained')

#         ax[0].imshow(np.flipud(label_mag[i]), vmin=0, vmax=mag_vmax, cmap='jet')
#         print("label mag is ", label_mag[i])
#         ax[1].imshow(np.flipud(pred_mag[i]), vmin=0, vmax=mag_vmax, cmap='jet')
#         print("pred mag is ", pred_mag[i])
#         ax[0].axis('off')
#         ax[0].axis('off')
#         # ax[1,0].imshow(np.flipud(label.vely[i]), vmin=0, vmax=mag_vmax, cmap='jet')
#         # ax[1,1].imshow(np.flipud(pred.vely[i]), vmin=0, vmax=mag_vmax, cmap='jet')

#         # ax[1,0].axis('off')
#         # ax[1,1].axis('off')

#         im_path = Path(path)
#         im_path.mkdir(parents=True, exist_ok=True)
#         plt.savefig(f'{str(im_path)}/{i_str}.png',
#                     dpi=200,
#                     bbox_inches='tight',
#                     transparent=True)
#         plt.close()
if __name__ == '__main__':
    main()
