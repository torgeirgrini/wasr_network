import os

import numpy as np
import tensorflow as tf


def image_scaling(img, label, imu):
    """
    Randomly scales the images between 0.5 to 1.5 times the original size.

    Args:
      img: Training image to scale.
      label: Segmentation mask to scale.
    """
    
    scale = tf.random.uniform([1], minval=0.5, maxval=1.5, dtype=tf.float32, seed=None)
    h_new = tf.cast(tf.multiply(tf.cast(tf.shape(img)[0], dtype=tf.float32), scale), dtype=tf.int32)
    w_new = tf.cast(tf.multiply(tf.cast(tf.shape(img)[1], dtype=tf.float32), scale), dtype=tf.int32)
    new_shape = tf.squeeze(tf.stack([h_new, w_new]), axis=[1])

    img = tf.image.resize(img, new_shape)

    label = tf.image.resize(tf.expand_dims(label, 0), new_shape, method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)
    label = tf.squeeze(label, axis=[0])

    imu = tf.image.resize(tf.expand_dims(imu, 0), new_shape, method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)
    imu = tf.squeeze(imu, axis=[0])
   
    return img, label, imu


def image_mirroring(img, label, imu):
    """
    Randomly mirrors the images.

    Args:
      img: Training image to mirror.
      label: Segmentation mask to mirror.
    """
    
    distort_left_right_random = tf.random.uniform([1], 0, 1.0, dtype=tf.float32)[0]
    mirror = tf.less(tf.stack([1.0, distort_left_right_random, 1.0]), 0.5)
    mirror = tf.boolean_mask([0, 1, 2], mirror)

    img = tf.reverse(img, mirror)

    label = tf.reverse(label, mirror)

    imu = tf.reverse(imu, mirror)

    return img, label, imu


def random_crop_and_pad_image_and_labels(image, label, imu, crop_h, crop_w, ignore_label=255):
    """
    Randomly crop and pads the input images.

    Args:
      image: Training image to crop/ pad.
      label: Segmentation mask to crop/ pad.
      crop_h: Height of cropped segment.
      crop_w: Width of cropped segment.
      ignore_label: Label to ignore during the training.
    """

    label = tf.cast(label, dtype=tf.float32)
    label = label - ignore_label # Needs to be subtracted and later added due to 0 padding.

    imu = tf.cast(imu, dtype=tf.float32)
	# We are not cropping the images
    #imu = tf.cast(imu, dtype=tf.float32)
    #imu = imu - ignore_label

    combined = tf.concat(axis=2, values=[image, label, imu])
    print(combined.shape)
    image_shape = tf.shape(image)
    combined_pad = tf.image.pad_to_bounding_box(combined, 0, 0, tf.maximum(crop_h, image_shape[0]),
                                                tf.maximum(crop_w, image_shape[1]))
    
    last_image_dim = tf.shape(image)[-1]
    last_label_dim = last_image_dim + tf.shape(label)[-1]

    combined_crop = tf.image.random_crop(combined_pad, [crop_h, crop_w, 5])

    print('combined crop')
    print(combined_crop.shape)

    img_crop = combined_crop[:, :, :last_image_dim]


    label_crop = combined_crop[:, :, last_image_dim:last_label_dim]
    label_crop = label_crop + ignore_label
    label_crop = tf.cast(label_crop, dtype=tf.uint8)

    imu_crop = combined_crop[:, :, last_label_dim:]

    # Set static shape so that tensorflow knows shape at compile time. 
    img_crop.set_shape((crop_h, crop_w, 3))

    label_crop.set_shape((crop_h,crop_w, 1))

    imu_crop.set_shape((crop_h,crop_w, 1))

    return img_crop, label_crop, imu_crop

def read_labeled_image_list(data_dir, data_list):
    """Reads txt file containing paths to images and ground truth masks.
    
    Args:
      data_dir: path to the directory with images and masks.
      data_list: path to the file with lines of the form '/path/to/image /path/to/mask'.
       
    Returns:
      Two lists with all file names for images and masks, respectively.
    """
    f = open(data_list, 'r')
    images = []
    gt_masks = []
    imu_masks = []
    for line in f:
        image, gt_mask, imu_mask = line.strip("\r\n").split(' ')
        #print(image)
        #print(mask)
        #try:
        #    image, mask = line.strip("\r\n").split(' ')
        #except ValueError: # Adhoc for test.
        #   image = mask = line.split(' ')
        #images.append(data_dir + image)
        #masks.append(data_dir + mask)
        images.append(data_dir + image)
        gt_masks.append(data_dir + gt_mask)
        imu_masks.append(data_dir + imu_mask)

    return images, gt_masks, imu_masks

def read_images_from_disk(input_queue, input_size, random_scale, random_mirror, ignore_label, img_mean): # optional pre-processing arguments
    """Read one image and its corresponding mask with optional pre-processing.
    
    Args:
      input_queue: tf queue with paths to the image and its mask.
      input_size: a tuple with (height, width) values.
                  If not given, return images of original size.
      random_scale: whether to randomly scale the images prior
                    to random crop.
      random_mirror: whether to randomly mirror the images prior
                    to random crop.
      ignore_label: index of label to ignore during the training.
      img_mean: vector of mean colour values.
      
    Returns:
      Two tensors: the decoded image and its mask.
    """
    img_contents = tf.io.read_file(input_queue[0])
    label_contents = tf.io.read_file(input_queue[1])
    imu_contents = tf.io.read_file(input_queue[2])
    
    img = tf.image.decode_jpeg(img_contents, channels=3)
    # Extract mean.
    img = tf.cast(img, dtype=tf.float32)
    img -= img_mean

    label = tf.image.decode_png(label_contents, channels=1)

    imu = tf.image.decode_png(imu_contents, channels=1)

    if input_size is not None:
        h, w = input_size

        # Randomly scale the images and labels.
        if random_scale:
            img, label, imu = image_scaling(img, label, imu)

        # Randomly mirror the images and labels.
        if random_mirror:
            img, label, imu = image_mirroring(img, label, imu)

        # Randomly crops the images and labels.
        img, label, imu = random_crop_and_pad_image_and_labels(img, label, imu, h, w, ignore_label)

    return img, label, imu


class ImageReader(object):
    '''Generic ImageReader which reads images and corresponding segmentation
       masks from the disk, and enqueues them into a TensorFlow queue.
    '''

    def __init__(self, data_dir, data_list, input_size, 
                 random_scale, random_mirror, ignore_label, img_mean, coord):
        '''Initialise an ImageReader.
        
        Args:
          data_dir: path to the directory with images and masks.
          data_list: path to the file with lines of the form '/path/to/image /path/to/mask'.
          input_size: a tuple with (height, width) values, to which all the images will be resized.
          random_scale: whether to randomly scale the images prior to random crop.
          random_mirror: whether to randomly mirror the images prior to random crop.
          ignore_label: index of label to ignore during the training.
          img_mean: vector of mean colour values.
          coord: TensorFlow queue coordinator.
        '''
        self.data_dir = data_dir
        self.data_list = data_list
        self.input_size = input_size
        self.coord = coord
        
        self.image_list, self.label_list, self.imu_list = read_labeled_image_list(self.data_dir, self.data_list)
        self.images = tf.convert_to_tensor(self.image_list, dtype=tf.string)
        self.labels = tf.convert_to_tensor(self.label_list, dtype=tf.string)
        self.imus = tf.convert_to_tensor(self.imu_list, dtype=tf.string)

        self.queue = tf.compat.v1.train.slice_input_producer([self.images, self.labels, self.imus]) # no shuffling. we have it preshuffled
                                                   #shuffle=input_size is not None) # not shuffling if it is val
        self.image, self.label, self.imu = read_images_from_disk(self.queue, self.input_size, random_scale, random_mirror, ignore_label, img_mean)

    def dequeue(self, num_elements):
        '''Pack images and labels into a batch.
        
        Args:
          num_elements: the batch size.
          
        Returns:
          Two tensors of size (batch_size, h, w, {3, 1}) for images and masks.'''
        image_batch, label_batch, imu_batch = tf.compat.v1.train.batch([self.image, self.label, self.imu],
                                                  num_elements)
        return image_batch, label_batch, imu_batch
