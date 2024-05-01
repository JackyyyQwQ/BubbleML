import os
import numpy as np
import torch
from torch.utils.data import ConcatDataset, Dataset
import h5py
import random
from torchvision.transforms import Resize
import torchvision.transforms.functional as TF
from pathlib import Path
#for nucleation 
from .nucleation import heater_init, dfun_init

class DiskHDF5Dataset(Dataset):
    def __init__(self,
                 filename,
                 steady_time,
                 transform=False,
                 time_window=1,
                 future_window=1,
                 push_forward_steps=1):
        super().__init__()
        assert time_window > 0, 'HDF5Dataset.__init__():time window should be positive'
        self.steady_time = steady_time
        self.transform = transform
        self.time_window = time_window
        self.future_window = future_window
        self.push_forward_steps = push_forward_steps
        
        self._data = h5py.File(filename, 'r')

        # these values are used to redimensionalize and then normalize data 
        self.wall_temp = self._get_wall_temp(filename)
        self.temp_scale = None
        self.vel_scale = None

    def datum_dim(self):
        return self._data['temperature'][:].shape

    def __len__(self):
        # len is the number of timesteps. Each prediction
        # requires time_window frames, so we can't predict for
        # the first few frames.
        # we may also predict several frames in the future, so we
        # can't include those in length
        total_size = self._data['temperature'].shape[0] - self.steady_time
        return total_size - self.time_window - (self.future_window * self.push_forward_steps - 1) 

    def _index_data(self, key, timestep):
        return self._data[key][self.steady_time + timestep]

    def _get_data(self, key):
        return self._data[key][self.steady_time:]

    def _get_wall_temp(self, filename):
        r"""
        Each hdf5 file non-dimensionalizes temperature to the same range. 
        If the wall temperature is varied across simulations, then the temperature
        must be re-dimensionalized, so it can be properly normalized across
        simulations.
        this is ONLY DONE WHEN THE FILENAME INCLUDES Twall-
        """
        filename = Path(filename).stem
        wall_temp = None
        TWALL = 'Twall-'
        if TWALL not in filename:
            # if temperature doesn't vary, no need to redim/normalize it
            return 1
        return float(filename[len(TWALL):])

    def absmax_temp(self):
        return np.abs(self._get_data('temperature') * self.wall_temp).max()

    def absmax_vel(self):
        return max(np.abs(self._get_data('velx')).max(), np.abs(self._get_data('vely')).max())

    def normalize_temp_(self, scale):
        self.temp_scale = scale

    def normalize_vel_(self, scale):
        self.vel_scale = scale

    def get_dy(self):
        r""" dy is the grid spacing in the y direction.
        """
        return self._get_data('y')[0, 0, 0]

    def get_dfun(self):
        return torch.from_numpy(self._get_data('dfun')[self.time_window:])

    def _get_temp(self, timestep):
        assert self.temp_scale is not None, 'Normalize not called?'
        temp = torch.from_numpy(self._index_data('temperature', timestep))
        return (2 * (temp * self.wall_temp) / self.temp_scale) - 1

    def _get_vel_stack(self, timestep):
        assert self.vel_scale is not None, 'Normalize not called?'
        vel = torch.stack([
            torch.from_numpy(self._index_data('velx', timestep)),
            torch.from_numpy(self._index_data('vely', timestep)),
        ], dim=0)
        return vel / self.vel_scale

    def _get_coords(self, timestep):
        x = torch.from_numpy(self._index_data('x', timestep))
        x /= x.max()
        y = torch.from_numpy(self._index_data('y', timestep))
        y /= y.max()
        coords = torch.stack([
            x, y
        ], dim=0)
        return coords

    def _get_dfun(self, timestep):
        vapor_mask = torch.from_numpy(self._index_data('dfun', timestep)) > 0
        return vapor_mask.to(float) - 0.5

    def _transform(self, *args):
        if self.transform:
            if random.random() > 0.5:
                args = tuple([TF.hflip(arg) for arg in args])
        return args

    def __getitem__(self, timestep):
        assert False, 'Not Implemented'

class DiskTempInputDataset(DiskHDF5Dataset):
    r""" 
    This is a dataset for predicting only temperature. It assumes that
    velocities are known in every timestep. It also enables writing
    past predictions for temperature and using them to make future
    predictions.
    """
    def __init__(self, filename, steady_time, use_coords, transform=False, time_window=1, future_window=1, push_forward_steps=1):
        super().__init__(filename, steady_time, transform, time_window, future_window, push_forward_steps)
        coords_dim = 2 if use_coords else 0
        self.in_channels = 3 * self.time_window + coords_dim + 2 * self.future_window
        self.out_channels = self.future_window

    def __getitem__(self, timestep):
        coords = self._get_coords(timestep)
        temps = torch.stack([self._get_temp(timestep + k) for k in range(self.time_window)], dim=0)
        vel = torch.cat([self._get_vel_stack(timestep + k) for k in range(self.time_window + self.future_window)], dim=0) 
        base_time = timestep + self.time_window 
        label = torch.stack([self._get_temp(base_time + k) for k in range(self.future_window)], dim=0)
        return (coords, *self._transform(temps, vel, label))
        
class DiskVelInputDataset(DiskHDF5Dataset):
    r""" 
    This is a dataset for predicting only velocity. It assumes that
    dfun are known at t and t+1, vel at t is also known. It also enables writing
    past predictions for velocities and using them to make future
    predictions.
    """
    def __init__(self,
                 filename,
                 steady_time,
                 use_coords,
                 transform=False,
                 time_window=1,
                 future_window=1,
                 push_forward_steps=1):
        super().__init__(filename, steady_time, transform, time_window, future_window, push_forward_steps)
        self.in_channels = 3 * self.time_window  #2 for current velocity 1 for current dfun 
        self.out_channels =2 * self.future_window #for two future velocity vx and vy 

    def __getitem__(self, timestep):
        # past velocity
        vel = torch.cat([self._get_vel_stack(timestep + k) for k in range(self.time_window)], dim=0).unsqueeze(0);
        base_time = timestep + self.time_window 
        label = torch.cat([self._get_vel_stack(base_time + k) for k in range(self.future_window)], dim=0).unsqueeze(0);
        # past and future dfun
        dfun = torch.stack([self._get_dfun(timestep + k) for k in range(self.time_window)], dim=0).unsqueeze(0);
        return self._transform(vel, dfun, label)
        
class DiskVelCoordInputDataset(DiskHDF5Dataset):
    r""" 
    This is a dataset for predicting only velocity. It assumes that
    dfun are known at t , vel at t is also known. It also enables writing
    past predictions for velocities and using them to make future
    predictions.
    """
    def __init__(self,
                 filename,
                 steady_time,
                 use_coords,
                 transform=False,
                 time_window=1,
                 future_window=1,
                 push_forward_steps=1):
        super().__init__(filename, steady_time, transform, time_window, future_window, push_forward_steps)
        coords_dim = 2 if use_coords else 0
        self.in_channels = coords_dim + 3 * self.time_window #2 for current velocity 1 for current dfun 
        self.out_channels =2 * self.future_window #for two future velocity vx and vy 

    def __getitem__(self, timestep):
        coords = self._get_coords(timestep).unsqueeze(0)
        # past velocity
        vel = torch.cat([self._get_vel_stack(timestep + k) for k in range(self.time_window)], dim=0).unsqueeze(0)
        base_time = timestep + self.time_window 
        label = torch.cat([self._get_vel_stack(base_time + k) for k in range(self.future_window)], dim=0).unsqueeze(0)
        # past and future dfun
        dfun = torch.stack([self._get_dfun(timestep + k) for k in range(self.time_window)], dim=0).unsqueeze(0)
        return self._transform(coords, vel, dfun, label)

class DiskVelDfunDataset(DiskHDF5Dataset):
    r""" 
    This is a dataset for predicting only velocity. It assumes that
    dfun are known at t , vel at t is also known. It also enables writing
    past predictions for velocities and using them to make future
    predictions.
    """
    def __init__(self,
                 filename,
                 steady_time,
                 use_coords,
                 transform=False,
                 time_window=1,
                 future_window=1,
                 push_forward_steps=1):
        super().__init__(filename, steady_time, transform, time_window, future_window, push_forward_steps)
        self.filename = filename
        coords_dim = 2 if use_coords else 0
        self.in_channels = 3 * self.time_window + 1 #2 for current velocity 1 for current dfun 1 for nucleation layer 
        self.out_channels =3 * self.future_window #for two future velocity vx and vy and 1 future dfun 

    #added function to get num sites based on different files 
    def get_num_sites(self, filename):
        r"""
        Extracts the Twall value from the filename and maps it to the corresponding
        number of nucleation sites.
        """
        filename = Path(filename).stem
        TWALL_PREFIX = 'Twall-'
        # Define a mapping from Twall value to the number of nucleation sites.
        twall_to_num_sites_map = {
            '90': 15, '92': 17, '95': 19, '97': 21, '98': 22,
            '100': 24, '102': 25, '106': 27, '108': 27, '110': 27
        }
        # Extract Twall value and convert it to an integer.
        twall_value = filename.split(TWALL_PREFIX)[-1]
        # Return the number of nucleation sites from the map.
        return twall_to_num_sites_map.get(twall_value, 0) 
        
    def __getitem__(self, timestep):
        # past velocity
        vel = torch.cat([self._get_vel_stack(timestep + k) for k in range(self.time_window)], dim=0).unsqueeze(0)
        base_time = timestep + self.time_window 
        vel_label = torch.cat([self._get_vel_stack(base_time + k) for k in range(self.future_window)], dim=0).unsqueeze(0)
        # past dfun
        dfun = torch.stack([self._get_dfun(timestep + k) for k in range(self.time_window)], dim=0).unsqueeze(0)
        dfun_label = torch.stack([self._get_dfun(base_time + k) for k in range(self.future_window)], dim=0).unsqueeze(0)
        
        #for nucleation layer 
        #get the num_sites
        num_sites = self.get_num_sites(self.filename)
        # Get the coordinates of grids
        coordx, coordy = self._data['x'][0], self._data['y'][0]
        # Initialize nucleation sites
        init_nucl_coordx, init_nucl_coordy = heater_init(-5.0, 5.0, num_sites)
        # Initialize the layer
        nucleation_layer = dfun_init(coordx, coordy, init_nucl_coordx, init_nucl_coordy, seed_radius=0.1)
        nucleation_layer[nucleation_layer>=0] = 1
        nucleation_layer[nucleation_layer<0] = 0
        nucleation_layer = torch.tensor(nucleation_layer).unsqueeze(0).unsqueeze(0)
        #return self._transform(coords, vel, dfun, nucleation_layer, vel_label, dfun_label)
        # Apply transformations to elements that require it
        transformed_vel, transformed_dfun, transformed_layer, transformed_vel_label, transformed_dfun_label = self._transform(vel, dfun, nucleation_layer, vel_label, dfun_label)
    
        # Return all elements, combining transformed ones with the untransformed nucleation_layer
        return  transformed_vel, transformed_dfun, transformed_layer, transformed_vel_label, transformed_dfun_label


class DiskTempVelDataset(DiskHDF5Dataset):
    r"""
    This is a dataset for predicting both temperature and velocity.
    Velocities and temperatures are unknown. The model writes past
    predictions to reuse for future predictions.
    """
    def __init__(self,
                 filename,
                 steady_time,
                 use_coords,
                 transform=False,
                 time_window=1,
                 future_window=1,
                 push_forward_steps=1):
        super().__init__(filename, steady_time, transform, time_window, future_window, push_forward_steps)
        coords_dim = 2 if use_coords else 0
        self.temp_channels = self.time_window
        self.vel_channels = self.time_window * 2
        self.dfun_channels = self.time_window

        self.in_channels = coords_dim + self.temp_channels + self.vel_channels + self.dfun_channels
        self.out_channels = 3 * self.future_window

    def _get_timestep(self, timestep):
        r"""
        Get the window rooted at timestep.
        This includes the {timestep - self.time_window, ..., timestep - 1} as input
        and {timestep, ..., timestep + future_window - 1} as output
        """
        coords = self._get_coords(timestep)
        temp = torch.stack([self._get_temp(timestep + k) for k in range(self.time_window)], dim=0)
        vel = torch.cat([self._get_vel_stack(timestep + k) for k in range(self.time_window)], dim=0) 
        dfun = torch.stack([self._get_dfun(timestep + k) for k in range(self.time_window)], dim=0)

        base_time = timestep + self.time_window 
        temp_label = torch.stack([self._get_temp(base_time + k) for k in range(self.future_window)], dim=0)
        vel_label = torch.cat([self._get_vel_stack(base_time + k) for k in range(self.future_window)], dim=0)
        return self._transform(coords, temp, vel, dfun, temp_label, vel_label)

    def __getitem__(self, timestep):
        r"""
        Get the windows rooted at {timestep, timestep + self.future_window, ...}
        For each variable, the windows are concatenated into one tensor.
        """
        args = list(zip(*[self._get_timestep(timestep + k * self.future_window) for k in range(self.push_forward_steps)]))
        return tuple([torch.stack(arg, dim=0) for arg in args])

    #def write_vel(self, vel, timestep):
    #    base_time = timestep + self.time_window
    #    self._data['velx'][base_time:base_time + self.future_window] = vel[0::2].cpu().numpy()
    #    self._data['vely'][base_time:base_time + self.future_window] = vel[1::2].cpu().numpy()

    #def write_temp(self, temp, timestep):
    #    if temp.ndim == 2:
    #        temp.unsqueeze_(-1)
    #    base_time = timestep + self.time_window
    #    self._data['temperature'][base_time:base_time + self.future_window] = temp.cpu().numpy()
