from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import collections
import functools
import operator
import resnet
import util


class Model(resnet.Model):

    """ implementation of DCGAN in TensorFlow

    [1] [Unsupervised Representation Learning with Deep Convolutional Generative Adversarial Networks]
        (https://arxiv.org/pdf/1511.06434.pdf) by Alec Radford, Luke Metz, and Soumith Chintala, Nov 2015.
    """

    class Generator(object):

        def __init__(self, image_size, filters, bottleneck, version, block_params, final_conv_param, channels_first):

            self.image_size = image_size
            self.filters = filters
            self.bottleneck = bottleneck
            self.version = version
            self.block_params = block_params
            self.final_conv_param = final_conv_param
            self.channels_first = channels_first
            self.data_format = "channels_first" if channels_first else "channels_last"

        def __call__(self, inputs, training, reuse=False):

            block_fn = ((Model.bottleneck_block_v1 if self.version == 1 else Model.bottleneck_block_v2) if self.bottleneck else
                        (Model.building_block_v1 if self.version == 1 else Model.building_block_v2))

            projection_shortcut = Model.projection_shortcut

            with tf.variable_scope("generator", reuse=reuse):

                strides_product = functools.partial(functools.reduce, operator.mul)(
                    [block_param.strides for block_param in self.block_params]
                )

                inputs = tf.layers.dense(
                    inputs=inputs,
                    units=(
                        self.filters *
                        self.image_size[0] // strides_product *
                        self.image_size[1] // strides_product
                    )
                )

                inputs = util.chunk_images(
                    inputs=inputs,
                    image_size=[
                        self.image_size[0] // strides_product,
                        self.image_size[1] // strides_product
                    ],
                    data_format=self.data_format
                )

                if self.version == 1:

                    inputs = tf.nn.leaky_relu(inputs)

                for i, block_param in enumerate(self.block_params):

                    inputs = Model.block_layer(
                        inputs=inputs,
                        block_fn=block_fn,
                        blocks=block_param.blocks,
                        filters=self.filters >> i,
                        strides=block_param.strides,
                        projection_shortcut=projection_shortcut,
                        data_format=self.data_format,
                        training=training
                    )

                    inputs = util.up_sampling2d(2, self.data_format)(inputs)

                if self.version == 2:

                    inputs = tf.nn.leaky_relu(inputs)

                inputs = tf.layers.conv2d(
                    inputs=inputs,
                    filters=3,
                    kernel_size=self.final_conv_param.kernel_size,
                    strides=self.final_conv_param.strides,
                    padding="same",
                    data_format=self.data_format,
                    kernel_initializer=tf.variance_scaling_initializer(),
                )

                inputs = tf.nn.tanh(inputs)

                return inputs

    class Discriminator(object):

        def __init__(self, filters, initial_conv_param, bottleneck, version, block_params, channels_first):

            self.filters = filters
            self.initial_conv_param = initial_conv_param
            self.bottleneck = bottleneck
            self.version = version
            self.block_params = block_params
            self.channels_first = channels_first
            self.data_format = "channels_first" if channels_first else "channels_last"

        def __call__(self, inputs, training, reuse=False):

            block_fn = ((Model.bottleneck_block_v1 if self.version == 1 else Model.bottleneck_block_v2) if self.bottleneck else
                        (Model.building_block_v1 if self.version == 1 else Model.building_block_v2))

            projection_shortcut = Model.projection_shortcut

            with tf.variable_scope("discriminator", reuse=reuse):

                inputs = tf.layers.conv2d(
                    inputs=inputs,
                    filters=self.filters,
                    kernel_size=self.initial_conv_param.kernel_size,
                    strides=self.initial_conv_param.strides,
                    padding="same",
                    data_format=self.data_format,
                    use_bias=False,
                    kernel_initializer=tf.variance_scaling_initializer(),
                )

                if self.version == 1:

                    inputs = tf.nn.leaky_relu(inputs)

                for i, block_param in enumerate(self.block_params):

                    inputs = Model.block_layer(
                        inputs=inputs,
                        block_fn=block_fn,
                        blocks=block_param.blocks,
                        filters=self.filters << i,
                        strides=block_param.strides,
                        projection_shortcut=projection_shortcut,
                        data_format=self.data_format,
                        training=training
                    )

                    inputs = tf.layers.average_pooling2d(
                        inputs=inputs,
                        pool_size=2,
                        strides=2,
                        padding="same",
                        data_format=self.data_format
                    )

                if self.version == 2:

                    inputs = tf.nn.leaky_relu(inputs)

                inputs = util.global_average_pooling2d(self.data_format)(inputs)

                inputs = tf.layers.dense(
                    inputs=inputs,
                    units=1
                )

                return inputs

    @staticmethod
    def building_block_v1(inputs, filters, strides, projection_shortcut, data_format, training):

        shortcut = inputs

        if projection_shortcut:

            shortcut = projection_shortcut(
                inputs=inputs,
                filters=filters,
                strides=strides,
                data_format=data_format
            )

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters,
            kernel_size=3,
            strides=strides,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs = tf.nn.leaky_relu(inputs)

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters,
            kernel_size=3,
            strides=1,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs += shortcut

        inputs = tf.nn.leaky_relu(inputs)

        return inputs

    @staticmethod
    def building_block_v2(inputs, filters, strides, projection_shortcut, data_format, training):

        shortcut = inputs

        inputs = tf.nn.leaky_relu(inputs)

        if projection_shortcut:

            shortcut = projection_shortcut(
                inputs=inputs,
                filters=filters,
                strides=strides,
                data_format=data_format
            )

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters,
            kernel_size=3,
            strides=strides,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs = tf.nn.leaky_relu(inputs)

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters,
            kernel_size=3,
            strides=1,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs += shortcut

        return inputs

    @staticmethod
    def bottleneck_block_v1(inputs, filters, strides, projection_shortcut, data_format, training):

        shortcut = inputs

        if projection_shortcut:

            shortcut = projection_shortcut(
                inputs=inputs,
                filters=filters << 2,
                strides=strides,
                data_format=data_format
            )

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters,
            kernel_size=1,
            strides=1,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs = tf.nn.leaky_relu(inputs)

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters,
            kernel_size=3,
            strides=strides,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs = tf.nn.leaky_relu(inputs)

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters << 2,
            kernel_size=1,
            strides=1,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs += shortcut

        inputs = tf.nn.leaky_relu(inputs)

        return inputs

    @staticmethod
    def bottleneck_block_v2(inputs, filters, strides, projection_shortcut, data_format, training):

        shortcut = inputs

        inputs = tf.nn.leaky_relu(inputs)

        if projection_shortcut:

            shortcut = projection_shortcut(
                inputs=inputs,
                filters=filters << 2,
                strides=strides,
                data_format=data_format
            )

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters,
            kernel_size=1,
            strides=1,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs = tf.nn.leaky_relu(inputs)

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters,
            kernel_size=3,
            strides=strides,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs = tf.nn.leaky_relu(inputs)

        inputs = tf.layers.conv2d(
            inputs=inputs,
            filters=filters << 2,
            kernel_size=1,
            strides=1,
            padding="same",
            data_format=data_format,
            use_bias=False,
            kernel_initializer=tf.variance_scaling_initializer(),
        )

        inputs += shortcut

        return inputs
