import os
import numpy as np
import math
import json
import argparse
import trimesh


def visualize_poses(poses, size=0.1):
    # poses: [B, 4, 4]
    print(f'[vis poses] {poses.shape} average center: {poses[:, :3, 3].mean(0)}')

    axes = trimesh.creation.axis(axis_length=4)
    sphere = trimesh.creation.icosphere(radius=1)
    objects = [sphere, axes]

    for pose in poses:
        # a camera is visualized with 8 line segments.
        pos = pose[:3, 3]
        
        a = pos + size * pose[:3, 0] + size * pose[:3, 1] + size * pose[:3, 2]
        b = pos - size * pose[:3, 0] + size * pose[:3, 1] + size * pose[:3, 2]
        c = pos - size * pose[:3, 0] - size * pose[:3, 1] + size * pose[:3, 2]
        d = pos + size * pose[:3, 0] - size * pose[:3, 1] + size * pose[:3, 2]

        segs = np.array([[pos, a], [pos, b], [pos, c], [pos, d], [a, b], [b, c], [c, d], [d, a]])
        segs = trimesh.load_path(segs)
        objects.append(segs)

    trimesh.Scene(objects).show()

# returns point closest to both rays of form o+t*d, and a weight factor that goes to 0 if the lines are parallel
def closest_point_2_lines(oa, da, ob, db): 
    da = da / np.linalg.norm(da)
    db = db / np.linalg.norm(db)
    c = np.cross(da, db)
    denom = np.linalg.norm(c)**2
    t = ob - oa
    ta = np.linalg.det([t, db, c]) / (denom + 1e-10)
    tb = np.linalg.det([t, da, c]) / (denom + 1e-10)
    if ta > 0:
        ta = 0
    if tb > 0:
        tb = 0
    return (oa+ta*da+ob+tb*db) * 0.5, denom

def rotmat(a, b):
	a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
	v = np.cross(a, b)
	c = np.dot(a, b)
	# handle exception for the opposite direction input
	if c < -1 + 1e-10:
		return rotmat(a + np.random.uniform(-1e-2, 1e-2, 3), b)
	s = np.linalg.norm(v)
	kmat = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
	return np.eye(3) + kmat + kmat.dot(kmat) * ((1 - c) / (s ** 2 + 1e-10))

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=str, help="root directory to the HyperNeRF dataset (contains camera/, rgb/, dataset.json, scene.json)")
    parser.add_argument('--downscale', type=int, default=2, help="image size down scale, choose from [2, 4, 8, 16], e.g., 8")

    opt = parser.parse_args()
    
    #print(f'[WARN]')

    print(f'[INFO] process {opt.path}')
    
    # load data
    with open(os.path.join(opt.path, 'dataset.json'), 'r') as f:
        json_dataset = json.load(f)

    N = json_dataset['count']
    ids = json_dataset['ids']

    with open(os.path.join(opt.path, 'scene.json'), 'r') as f:
        json_scene = json.load(f)

    scale = json_scene['scale']
    center = json_scene['center']

    with open(os.path.join(opt.path, 'metadata.json'), 'r') as f:
        json_meta = json.load(f)

    # seems there is no val_ids, we convert it to colmap mode (only a transforms.json)
    
    images = []
    times = []
    poses = []
    H, W, f, cx, cy = None, None, None, None, None
    for idx in ids:
        # load image
        images.append(os.path.join('rgb', f'{opt.downscale}x', f'{idx}.png'))

        # load time
        times.append(json_meta[idx]['time_id'])

        # load pose
        with open(os.path.join(opt.path, 'camera', f'{idx}.json'), 'r') as f:
            cam = json.load(f)
        # we use a simplified camera model rather than the original openCV camera model... hope it won't influence results seriously...
        pose = np.eye(4, 4)
        pose[:3, :3] = np.array(cam['orientation'])
        pose[:3, 3] = (np.array(cam['position']) - center) * scale * 3

        # CHECK: simply assume all intrinsic are same ?
        H, W = cam['image_size'] # before scale
        cx, cy = cam['principal_point']
        fl = cam['focal_length']

        poses.append(pose)

    poses = np.stack(poses, axis=0) # [N, 4, 4]
    times = np.asarray(times, dtype=np.float32) # [N]
    times = times / times.max() # normalize to [0, 1]

    H = H // opt.downscale
    W = W // opt.downscale
    cx = cx / opt.downscale
    cy = cy / opt.downscale
    fl = fl / opt.downscale

    print(f'[INFO] H = {H}, W = {W}, fl = {fl} (downscale = {opt.downscale})')

    # simple flip
    # poses[:, :, 1] *= -1
    # poses[:, :, 2] *= -1
    
    # # the following stuff are from colmap2nerf... 
    poses[:, 0:3, 1] *= -1
    poses[:, 0:3, 2] *= -1
    poses = poses[:, [1, 0, 2, 3], :] # swap y and z
    poses[:, 2, :] *= -1 # flip whole world upside down

    up = poses[:, 0:3, 1].sum(0)
    up = up / np.linalg.norm(up)
    R = rotmat(up, [0, 0, 1]) # rotate up vector to [0,0,1]
    R = np.pad(R, [0, 1])
    R[-1, -1] = 1

    poses = R @ poses

    # totw = 0.0
    # totp = np.array([0.0, 0.0, 0.0])
    # for i in range(N):
    #     mf = poses[i, :3, :]
    #     for j in range(i + 1, N):
    #         mg = poses[j, :3, :]
    #         p, w = closest_point_2_lines(mf[:,3], mf[:,2], mg[:,3], mg[:,2])
    #         #print(i, j, p, w)
    #         if w > 0.01:
    #             totp += p * w
    #             totw += w
    # totp /= totw
    # print(f'[INFO] totp = {totp}')
    # poses[:, :3, 3] -= totp

    # avglen = np.linalg.norm(poses[:, :3, 3], axis=-1).mean()

    # poses[:, :3, 3] *= 4.0 / avglen

    # print(f'[INFO] average radius = {avglen}')

    visualize_poses(poses)

    # construct frames
    frames = []
    for i in range(N):
        frames.append({
            'file_path': images[i],
            'time': float(times[i]),
            'transform_matrix': poses[i].tolist(),
        })

    # construct a transforms.json
    transforms = {
        'w': W,
        'h': H,
        'fl_x': fl,
        'fl_y': fl,
        'cx': cx,
        'cy': cy,
        'frames': frames,
    }

    # write
    output_path = os.path.join(opt.path, 'transforms.json')
    print(f'[INFO] write to {output_path}')
    with open(output_path, 'w') as f:
        json.dump(transforms, f, indent=2)

