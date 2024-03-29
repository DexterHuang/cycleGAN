import numpy as np
from tqdm import trange, tqdm
import glob
import h5py
from keras.optimizers import Adam
from keras import backend as K
from keras.preprocessing import image
import random
from models import components, mae_loss, mse_loss
import scipy.misc
# Avoid crash on non-X linux sessions (tipically servers) when plotting images
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import gc
import time
from glob import glob

# Images size
w = 256
h = 256

# Cyclic consistency factor

lmda = 10

# Optimizer parameters

lr = 0.0002
beta_1 = 0.5
beta_2 = 0.999
epsilon = 1e-08

# Setting image format as (channels, height, width)
K.set_image_dim_ordering('th')

disc_a_history = []
disc_b_history = []

gen_a2b_history = {'bc': [], 'mae': []}
gen_b2a_history = {'bc': [], 'mae': []}

gen_b2a_history_new = []
gen_a2b_history_new = []
cycle_history = []

model_save_folder = "models"


# Data loading

def loadImage(path, h, w):
    '''Load single image from specified path'''
    if path in cache:
      return cache[path]
    img = image.load_img(path)
    img = img.resize((w, h))
    x = image.img_to_array(img)
    cache[path] = x
    return x

def loadImagesFromDataset(h, w, dataset, use_hdf5=False):
    '''Return a tuple (trainA, trainB, testA, testB)
    containing numpy arrays populated from the
     test and train set for each part of the cGAN'''

    if (use_hdf5):
        path = "./datasets/processed/" + dataset + "_data.h5"
        data = []
        print('\n', '-' * 15, 'Loading data from dataset', dataset, '-' * 15)
        with h5py.File(path, "r") as hf:
            for set_name in tqdm(["trainA_data", "trainB_data", "testA_data", "testB_data"]):
                data.append(hf[set_name][:].astype(np.float32))

        return (set_data for set_data in data)

    else:
        path = "./datasets/" + dataset
        print(path)
        train_a = glob.glob(path + "/trainA/*.jpg")
        train_b = glob.glob(path + "/trainB/*.jpg")
        test_a = glob.glob(path + "/testA/*.jpg")
        test_b = glob.glob(path + "/testB/*.jpg")

        print("Import trainA")
        if dataset == "nike2adidas" or ("adiedges" in dataset):
            tr_a = np.array([loadImage(p, h, w) for p in tqdm(train_a[:1000])])
        else:
            tr_a = np.array([loadImage(p, h, w) for p in tqdm(train_a)])

        print("Import trainB")
        if dataset == "nike2adidas" or ("adiedges" in dataset):
            tr_b = np.array([loadImage(p, h, w) for p in tqdm(train_b[:1000])])
        else:
            tr_b = np.array([loadImage(p, h, w) for p in tqdm(train_b)])

        print("Import testA")
        ts_a = np.array([loadImage(p, h, w) for p in tqdm(test_a)])

        print("Import testB")
        ts_b = np.array([loadImage(p, h, w) for p in tqdm(test_b)])

    return tr_a, tr_b, ts_a, ts_b
cache = dict()
n_batches = -1
current_milli_time = lambda: int(round(time.time() * 1000))
def load_batch(dataset, batch_size=1, is_testing=False, break_img=False):
    data_type = "train" if not is_testing else "test"
    a = f'./datasets/{dataset}/{data_type}A/*'
    b = f'./datasets/{dataset}/{data_type}B/*'
    path_A = None
    path_B = None
    if a in cache:
        path_A = cache[a]
    else:
        path_A = glob(a)

    if b in cache:
        path_B = cache[b]
    else:
        path_B = glob(b)

    n_batches = int(min(len(path_A), len(path_B)) / batch_size)
    total_samples = n_batches * batch_size

    # Sample n_batches * batch_size from each path list so that model sees all
    # samples from both domains
    path_A = np.random.choice(path_A, total_samples, replace=False)
    path_B = np.random.choice(path_B, total_samples, replace=False)

    for i in range(n_batches-1):
        start_time = current_milli_time()
        batch_A = path_A[i*batch_size:(i+1)*batch_size]
        batch_B = path_B[i*batch_size:(i+1)*batch_size]
        imgs_A, imgs_B = [], []
        for img_A, img_B in zip(batch_A, batch_B):
            img_B = load_img2(img_B, break_img=break_img)
            img_A = load_img2(img_A, break_img=break_img)


            imgs_A.append(img_A)
            imgs_B.append(img_B)

        imgs_A = np.array(imgs_A)/127.5 - 1.
        imgs_B = np.array(imgs_B)/127.5 - 1.

        yield imgs_A, imgs_B, current_milli_time() - start_time

def load_img2( path, break_img):
    name = path
    if name in cache:
        img = cache[name]
    else:
        img = loadImage(path, h , w)
        cache[name] = img
    return img
# Create a wall of generated images
def plotGeneratedImages(epoch, dataset, batch_size, generator_a2b, generator_b2a, examples=6):

    a1, b1, t = next(load_batch(dataset, batch_size, is_testing=True, ))
    a2, b2, t = next(load_batch(dataset, batch_size, is_testing=True, ))
    a3, b3, t = next(load_batch(dataset, batch_size, is_testing=True, ))
    a4, b4, t = next(load_batch(dataset, batch_size, is_testing=True, ))
    a5, b5, t = next(load_batch(dataset, batch_size, is_testing=True, ))
    a6, b6, t = next(load_batch(dataset, batch_size, is_testing=True, ))
    set_a= np.array([a1[0],a2[0],a3[0],a4[0],a5[0],a6[0]])
    set_b= np.array([b1[0],b2[0],b3[0],b4[0],b5[0],b6[0]])
    true_batch_a = set_a[np.random.randint(0, set_a.shape[0], size=examples)]
    true_batch_b = set_b[np.random.randint(0, set_b.shape[0], size=examples)]

    # Get fake and cyclic images
    generated_a2b = generator_a2b.predict(true_batch_a)
    cycle_a = generator_b2a.predict(generated_a2b)
    generated_b2a = generator_b2a.predict(true_batch_b)
    cycle_b = generator_a2b.predict(generated_b2a)

    k = 0

    # Allocate figure
    plt.figure(figsize=(w / 10, h / 10))

    for output in [true_batch_a, generated_a2b, cycle_a, true_batch_b, generated_b2a, cycle_b]:
        output = (output + 1.0) / 2.0
        for i in range(output.shape[0]):
            plt.subplot(examples, examples, k * examples + (i + 1))
            img = output[i].transpose(1, 2, 0)  # Using (ch, h, w) scheme needs rearranging for plt to (h, w, ch)
            # print(img.shape)
            plt.imshow(img)
            plt.axis('off')
        plt.tight_layout()
        k += 1
    plt.savefig("images/epoch" + str(epoch) + ".png")
    plt.close()


# Plot the loss from each batch

def plotLoss_new():
    plt.figure(figsize=(10, 8))
    plt.plot(disc_a_history, label='Discriminator A loss')
    plt.plot(disc_b_history, label='Discriminator B loss')
    plt.plot(gen_a2b_history_new, label='Generator a2b loss')
    plt.plot(gen_b2a_history_new, label='Generator b2a loss')
    # plt.plot(cycle_history, label="Cyclic loss")
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    plt.legend()
    plt.savefig('images/cyclegan_loss.png')
    plt.close()


def saveModels(epoch, dataset, genA2B, genB2A, discA, discB):
    print("Saving Model...")
    genA2B.save(f'{model_save_folder}/{dataset}_{epoch}_{w}x{h}_generatorA2B.h5')
    genB2A.save(f'{model_save_folder}/{dataset}_{epoch}_{w}x{h}_generatorB2A.h5')
    discA.save(f'{model_save_folder}/{dataset}_{epoch}_{w}x{h}_discriminatorA.h5')
    discB.save(f'{model_save_folder}/{dataset}_{epoch}_{w}x{h}_discriminatorBh.h5')
    print("Model Saved!")


def loadModels(epoch, dataset, genA2B, genB2A, discA, discB):
    try:
        genA2B.load_weights(f'{model_save_folder}/{dataset}_{epoch}_{w}x{h}_generatorA2B.h5')
        genB2A.load_weights(f'{model_save_folder}/{dataset}_{epoch}_{w}x{h}_generatorB2A.h5')
        discA.load_weights(f'{model_save_folder}/{dataset}_{epoch}_{w}x{h}_discriminatorA.h5')
        discB.load_weights(f'{model_save_folder}/{dataset}_{epoch}_{w}x{h}_discriminatorB.h5')
    except Exception as e:
        print(f"Failed to load model: {e}")


# Training

def train(epochs, batch_size, dataset, baselr, use_pseudounet=False, use_unet=False, use_decay=False, plot_models=True,
          end_of_epoch_callback=None):
    if end_of_epoch_callback is not None:
        end_of_epoch_callback()

    # Load data and normalize
    # x_train_a, x_train_b, x_test_a, x_test_b = loadImagesFromDataset(h, w, dataset, use_hdf5=False)
    # x_train_a = (x_train_a.astype(np.float32) - 127.5) / 127.5
    # x_train_b = (x_train_b.astype(np.float32) - 127.5) / 127.5
    # x_test_a = (x_test_a.astype(np.float32) - 127.5) / 127.5
    # x_test_b = (x_test_b.astype(np.float32) - 127.5) / 127.5

    batchCount_a = n_batches
    batchCount_b = n_batches

    # Train on same image amount, would be best to have even sets
    batchCount = min([batchCount_a, batchCount_b])

    print('\nEpochs:', epochs)
    print('Batch size:', batch_size)
    print('Batches per epoch: ', batchCount, "\n")

    # Retrieve components and save model before training, to preserve weights initialization
    disc_a, disc_b, gen_a2b, gen_b2a = components(w, h, pseudounet=use_pseudounet, unet=use_unet, plot=plot_models)


    # LOAD AND SAVE ====
    loadModels('latest', dataset, gen_a2b, gen_b2a, disc_a, disc_b)
    # saveModels('latest', dataset, gen_a2b, gen_b2a, disc_a, disc_b)

    # Initialize fake images pools
    pool_a2b = []
    pool_b2a = []

    # Define optimizers
    adam_disc = Adam(lr=baselr, beta_1=0.5)
    adam_gen = Adam(lr=baselr, beta_1=0.5)

    # Define image batches
    true_a = gen_a2b.inputs[0]
    true_b = gen_b2a.inputs[0]

    fake_b = gen_a2b.outputs[0]
    fake_a = gen_b2a.outputs[0]

    fake_pool_a = K.placeholder(shape=(None, 3, h, w))
    fake_pool_b = K.placeholder(shape=(None, 3, h, w))

    # Labels for generator training
    y_fake_a = K.ones_like(disc_a([fake_a]))
    y_fake_b = K.ones_like(disc_b([fake_b]))

    # Labels for discriminator training
    y_true_a = K.ones_like(disc_a([true_a])) * 0.9
    y_true_b = K.ones_like(disc_b([true_b])) * 0.9

    fakelabel_a2b = K.zeros_like(disc_b([fake_b]))
    fakelabel_b2a = K.zeros_like(disc_a([fake_a]))

    # Define losses
    disc_a_loss = mse_loss(y_true_a, disc_a([true_a])) + mse_loss(fakelabel_b2a, disc_a([fake_pool_a]))
    disc_b_loss = mse_loss(y_true_b, disc_b([true_b])) + mse_loss(fakelabel_a2b, disc_b([fake_pool_b]))

    gen_a2b_loss = mse_loss(y_fake_b, disc_b([fake_b]))
    gen_b2a_loss = mse_loss(y_fake_a, disc_a([fake_a]))

    cycle_a_loss = mae_loss(true_a, gen_b2a([fake_b]))
    cycle_b_loss = mae_loss(true_b, gen_a2b([fake_a]))
    cyclic_loss = cycle_a_loss + cycle_b_loss

    # Prepare discriminator updater
    discriminator_weights = disc_a.trainable_weights + disc_b.trainable_weights
    disc_loss = (disc_a_loss + disc_b_loss) * 0.5
    discriminator_updater = adam_disc.get_updates(discriminator_weights, [], disc_loss)

    # Prepare generator updater
    generator_weights = gen_a2b.trainable_weights + gen_b2a.trainable_weights
    gen_loss = (gen_a2b_loss + gen_b2a_loss + lmda * cyclic_loss)
    generator_updater = adam_gen.get_updates(generator_weights, [], gen_loss)

    # Define trainers
    generator_trainer = K.function([true_a, true_b], [gen_a2b_loss, gen_b2a_loss, cyclic_loss], generator_updater)
    discriminator_trainer = K.function([true_a, true_b, fake_pool_a, fake_pool_b], [disc_a_loss / 2, disc_b_loss / 2],
                                       discriminator_updater)

    epoch_counter = 1

    plotGeneratedImages(epoch_counter,dataset, batch_size,  gen_a2b, gen_b2a)

    # Start training
    for e in range(1, epochs + 1):
        print('\n', '-' * 15, 'Epoch %d' % e, '-' * 15)
        gc.collect()

        # Learning rate decay
        if use_decay and (epoch_counter > 100):
            lr -= baselr / 100
            adam_disc.lr = lr
            adam_gen.lr = lr

        # Initialize progbar and batch counter
        # progbar = generic_utils.Progbar(batchCount)

        # np.random.shuffle(x_train_a)
        # np.random.shuffle(x_train_b)
        print(f"Batch count: {batchCount}")
        # Cycle through batches
        for i in trange(int(1000)):

            # Select true images for training
            # true_batch_a = x_train_a[np.random.randint(0, x_train_a.shape[0], size=batch_size)]
            # true_batch_b = x_train_b[np.random.randint(0, x_train_b.shape[0], size=batch_size)]

            true_batch_a, true_batch_b, load_time = next(load_batch(dataset, batch_size, is_testing=False, ))
            print(f"Load time: {load_time}")
            # true_batch_a = x_train_a[i * batch_size:i * batch_size + batch_size]
            # true_batch_b = x_train_b[i * batch_size:i * batch_size + batch_size]

            # Fake images pool
            a2b = gen_a2b.predict(true_batch_a)
            b2a = gen_b2a.predict(true_batch_b)

            tmp_b2a = []
            tmp_a2b = []

            for element in a2b:
                if len(pool_a2b) < 50:
                    pool_a2b.append(element)
                    tmp_a2b.append(element)
                else:
                    p = random.uniform(0, 1)

                    if p > 0.5:
                        index = random.randint(0, 49)
                        tmp = np.copy(pool_a2b[index])
                        pool_a2b[index] = element
                        tmp_a2b.append(tmp)
                    else:
                        tmp_a2b.append(element)

            for element in b2a:
                if len(pool_b2a) < 50:
                    pool_b2a.append(element)
                    tmp_b2a.append(element)
                else:
                    p = random.uniform(0, 1)

                    if p > 0.5:
                        index = random.randint(0, 49)
                        tmp = np.copy(pool_b2a[index])
                        pool_b2a[index] = element
                        tmp_b2a.append(tmp)
                    else:
                        tmp_b2a.append(element)

            pool_a = np.array(tmp_b2a)
            pool_b = np.array(tmp_a2b)

            # Update network and obtain losses
            disc_a_err, disc_b_err = discriminator_trainer([true_batch_a, true_batch_b, pool_a, pool_b])
            gen_a2b_err, gen_b2a_err, cyclic_err = generator_trainer([true_batch_a, true_batch_b])

            # progbar.add(1, values=[
            #                             ("D A", disc_a_err*2),
            #                             ("D B", disc_b_err*2),
            #                             ("G A2B loss", gen_a2b_err),
            #                             ("G B2A loss", gen_b2a_err),
            #                             ("Cyclic loss", cyclic_err)
            #                            ])

        # Save losses for plotting
        disc_a_history.append(disc_a_err)
        disc_b_history.append(disc_b_err)

        gen_a2b_history_new.append(gen_a2b_err)
        gen_b2a_history_new.append(gen_b2a_err)

        # cycle_history.append(cyclic_err[0])
        plotLoss_new()

        plotGeneratedImages(epoch_counter, dataset, batch_size,  gen_a2b, gen_b2a)

        saveModels(epoch_counter, dataset, gen_a2b, gen_b2a, disc_a, disc_b)
        saveModels('latest', dataset, gen_a2b, gen_b2a, disc_a, disc_b)

        epoch_counter += 1

        if end_of_epoch_callback is not None:
            end_of_epoch_callback()


def end_of_epoch_callback():
    print("potato")


if __name__ == '__main__':
    train(200, 1, "n-yandex", lr, use_decay=True, use_pseudounet=False, use_unet=False, plot_models=False,
          end_of_epoch_callback=end_of_epoch_callback)
# tensorflowjs_converter --input_format keras models/n-yandex_latest_256x256_generatorA2B.h5 out/