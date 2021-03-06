import time
import random
import pandas as pd
from glob import glob
import pprint
import argparse
import json
import subprocess
import sys
import os
import tensorflow as tf
#subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'tensorflow==2.1.0'])
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'transformers==2.8.0'])
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'sagemaker-tensorflow==2.1.0.1.0.0'])
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'smdebug==0.7.2'])
from transformers import DistilBertTokenizer
from transformers import TFDistilBertForSequenceClassification
from transformers import TextClassificationPipeline
from transformers.configuration_distilbert import DistilBertConfig

CLASSES = [1, 2, 3, 4, 5]

def select_data_and_label_from_record(record):
    x = {
        'input_ids': record['input_ids'],
        'input_mask': record['input_mask'],
        'segment_ids': record['segment_ids']
    }

    y = record['label_ids']

    return (x, y)


def file_based_input_dataset_builder(channel,
                                     input_filenames,
                                     pipe_mode,
                                     is_training,
                                     drop_remainder,
                                     batch_size,
                                     epochs,
                                     steps_per_epoch,
                                     max_seq_length):

    # For training, we want a lot of parallel reading and shuffling.
    # For eval, we want no shuffling and parallel reading doesn't matter.

    if pipe_mode:
        print('***** Using pipe_mode with channel {}'.format(channel))
        from sagemaker_tensorflow import PipeModeDataset
        dataset = PipeModeDataset(channel=channel,
                                  record_format='TFRecord')
    else:
        print('***** Using input_filenames {}'.format(input_filenames))
        dataset = tf.data.TFRecordDataset(input_filenames)

    dataset = dataset.repeat(epochs * steps_per_epoch)
    dataset = dataset.prefetch(tf.data.experimental.AUTOTUNE)

    name_to_features = {
      "input_ids": tf.io.FixedLenFeature([max_seq_length], tf.int64),
      "input_mask": tf.io.FixedLenFeature([max_seq_length], tf.int64),
      "segment_ids": tf.io.FixedLenFeature([max_seq_length], tf.int64),
      "label_ids": tf.io.FixedLenFeature([], tf.int64),
    }

    def _decode_record(record, name_to_features):
        """Decodes a record to a TensorFlow example."""
        record = tf.io.parse_single_example(record, name_to_features)
        # TODO:  wip/bert/bert_attention_head_view/train.py
        # Convert input_ids into input_tokens with DistilBert vocabulary 
        #  if hook.get_collections()['all'].save_config.should_save_step(modes.EVAL, hook.mode_steps[modes.EVAL]):
#              hook._write_raw_tensor_simple("input_tokens", input_tokens)
        return record
    
    dataset = dataset.apply(
        tf.data.experimental.map_and_batch(
          lambda record: _decode_record(record, name_to_features),
          batch_size=batch_size,
          drop_remainder=drop_remainder,
          num_parallel_calls=tf.data.experimental.AUTOTUNE))

    dataset.cache()

    if is_training:
        dataset = dataset.shuffle(seed=42,
                                  buffer_size=1000,
                                  reshuffle_each_iteration=True)

    return dataset


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--train_data', 
                        type=str, 
                        default=os.environ['SM_CHANNEL_TRAIN'])
    parser.add_argument('--validation_data', 
                        type=str, 
                        default=os.environ['SM_CHANNEL_VALIDATION'])
    parser.add_argument('--test_data',
                        type=str,
                        default=os.environ['SM_CHANNEL_TEST'])
    # This points to the S3 location - this should not be used by our code
    # We should use /opt/ml/model/ instead
#     parser.add_argument('--model_dir', 
#                         type=str, 
#                         default=os.environ['SM_MODEL_DIR'])
    parser.add_argument('--output_dir',
                        type=str,
                        default=os.environ['SM_OUTPUT_DIR'])
    # This is unused
    parser.add_argument('--output_data_dir',
                        type=str,
                        default=os.environ['SM_OUTPUT_DATA_DIR'])
    parser.add_argument('--hosts', 
                        type=list, 
                        default=json.loads(os.environ['SM_HOSTS']))
    parser.add_argument('--current_host', 
                        type=str, 
                        default=os.environ['SM_CURRENT_HOST'])    
    parser.add_argument('--num_gpus', 
                        type=int, 
                        default=os.environ['SM_NUM_GPUS'])
    parser.add_argument('--use_xla',
                        type=eval,
                        default=False)
    parser.add_argument('--use_amp',
                        type=eval,
                        default=False)
    parser.add_argument('--max_seq_length',
                        type=int,
                        default=128)
    parser.add_argument('--train_batch_size',
                        type=int,
                        default=128)
    parser.add_argument('--validation_batch_size',
                        type=int,
                        default=256)
    parser.add_argument('--test_batch_size',
                        type=int,
                        default=256)
    parser.add_argument('--epochs',
                        type=int,
                        default=2)
    parser.add_argument('--learning_rate',
                        type=float,
                        default=0.00003)
    parser.add_argument('--epsilon',
                        type=float,
                        default=0.00000001)
    parser.add_argument('--train_steps_per_epoch',
                        type=int,
                        default=1000)
    parser.add_argument('--validation_steps',
                        type=int,
                        default=1000)
    parser.add_argument('--test_steps',
                        type=int,
                        default=1000)
    parser.add_argument('--freeze_bert_layer',
                        type=eval,
                        default=False)
    parser.add_argument('--enable_sagemaker_debugger',
                        type=eval,
                        default=False)
    parser.add_argument('--run_validation',
                        type=eval,
                        default=False)    
    parser.add_argument('--run_test',
                        type=eval,
                        default=False)    
    parser.add_argument('--run_sample_predictions',
                        type=eval,
                        default=False)
    
    args, _ = parser.parse_known_args()
    print("Args:") 
    print(args)
    
    env_var = os.environ 
    print("Environment Variables:") 
    pprint.pprint(dict(env_var), width = 1) 

    train_data = args.train_data
    print('train_data {}'.format(train_data))
    validation_data = args.validation_data
    print('validation_data {}'.format(validation_data))
    test_data = args.test_data
    print('test_data {}'.format(test_data))    

#    model_dir = args.model_dir
#    print('model_dir {}'.format(model_dir))    
    local_model_dir = os.environ['SM_MODEL_DIR']

    output_dir = args.output_dir
    print('output_dir {}'.format(output_dir))    

    # This is unused
#    output_data_dir = args.output_data_dir
#    print('output_data_dir {}'.format(output_data_dir))    
    hosts = args.hosts
    print('hosts {}'.format(hosts))    
    current_host = args.current_host
    print('current_host {}'.format(current_host))    
    num_gpus = args.num_gpus
    print('num_gpus {}'.format(num_gpus))
    use_xla = args.use_xla
    print('use_xla {}'.format(use_xla))    
    use_amp = args.use_amp
    print('use_amp {}'.format(use_amp))    
    max_seq_length = args.max_seq_length
    print('max_seq_length {}'.format(max_seq_length))    
    train_batch_size = args.train_batch_size
    print('train_batch_size {}'.format(train_batch_size))    
    validation_batch_size = args.validation_batch_size
    print('validation_batch_size {}'.format(validation_batch_size))    
    test_batch_size = args.test_batch_size
    print('test_batch_size {}'.format(test_batch_size))    
    epochs = args.epochs
    print('epochs {}'.format(epochs))    
    learning_rate = args.learning_rate
    print('learning_rate {}'.format(learning_rate))    
    epsilon = args.epsilon
    print('epsilon {}'.format(epsilon))    
    train_steps_per_epoch = args.train_steps_per_epoch
    print('train_steps_per_epoch {}'.format(train_steps_per_epoch))    
    validation_steps = args.validation_steps
    print('validation_steps {}'.format(validation_steps))    
    test_steps = args.test_steps
    print('test_steps {}'.format(test_steps))    
    freeze_bert_layer = args.freeze_bert_layer
    print('freeze_bert_layer {}'.format(freeze_bert_layer))    
    enable_sagemaker_debugger = args.enable_sagemaker_debugger
    print('enable_sagemaker_debugger {}'.format(enable_sagemaker_debugger))    
    run_validation = args.run_validation
    print('run_validation {}'.format(run_validation))    
    run_test = args.run_test
    print('run_test {}'.format(run_test))    
    run_sample_predictions = args.run_sample_predictions
    print('run_sample_predictions {}'.format(run_sample_predictions))    

    # Determine if PipeMode is enabled 
    pipe_mode_str = os.environ.get('SM_INPUT_DATA_CONFIG', '')
    pipe_mode = (pipe_mode_str.find('Pipe') >= 0)
    print('Using pipe_mode: {}'.format(pipe_mode))
 
    # Model Output 
    transformer_fine_tuned_model_path = os.path.join(local_model_dir, 'transformers/fine-tuned/')
    os.makedirs(transformer_fine_tuned_model_path, exist_ok=True)

    # SavedModel Output
    tensorflow_saved_model_path = os.path.join(local_model_dir, 'tensorflow/saved_model/0')
    os.makedirs(tensorflow_saved_model_path, exist_ok=True)

    # Tensorboard Logs 
    tensorboard_logs_path = os.path.join(output_dir, 'tensorboard') 
    os.makedirs(tensorboard_logs_path, exist_ok=True)

    distributed_strategy = tf.distribute.MirroredStrategy()
    # smdebug currently (0.7.2) does not support MultiWorkerMirroredStrategy()
    # distributed_strategy = tf.distribute.experimental.MultiWorkerMirroredStrategy()
    with distributed_strategy.scope():
        tf.config.optimizer.set_jit(use_xla)
        tf.config.optimizer.set_experimental_options({"auto_mixed_precision": use_amp})

        train_data_filenames = glob(os.path.join(train_data, '*.tfrecord'))
        print('train_data_filenames {}'.format(train_data_filenames))
        train_dataset = file_based_input_dataset_builder(
            channel='train',
            input_filenames=train_data_filenames,
            pipe_mode=pipe_mode,
            is_training=True,
            drop_remainder=False,
            batch_size=train_batch_size,
            epochs=epochs,
            steps_per_epoch=train_steps_per_epoch,
            max_seq_length=max_seq_length).map(select_data_and_label_from_record)

        tokenizer = None
        config = None
        model = None

        # This is required when launching many instances at once...  the urllib request seems to get denied periodically
        successful_download = False
        retries = 0
        while (retries < 5 and not successful_download):
            try:
                tokenizer = DistilBertTokenizer.from_pretrained('distilbert-base-uncased')
                config = DistilBertConfig.from_pretrained('distilbert-base-uncased',
                                                          num_labels=len(CLASSES))
                model = TFDistilBertForSequenceClassification.from_pretrained('distilbert-base-uncased',
                                                                              config=config)
                successful_download = True
                print('Sucessfully downloaded after {} retries.'.format(retries))
            except:
                retries = retries + 1
                random_sleep = random.randint(1, 30)
                print('Retry #{}.  Sleeping for {} seconds'.format(retries, random_sleep))
                time.sleep(random_sleep)

        if not tokenizer or not model or not config:
            print('Not properly initialized...')

        optimizer = tf.keras.optimizers.Adam(learning_rate=learning_rate, epsilon=epsilon)
        print('** use_amp {}'.format(use_amp))        
        if use_amp:
            # loss scaling is currently required when using mixed precision
            optimizer = tf.keras.mixed_precision.experimental.LossScaleOptimizer(optimizer, 'dynamic')

        callbacks = []
        print('enable_sagemaker_debugger {}'.format(enable_sagemaker_debugger))
        if enable_sagemaker_debugger:
            print('*** DEBUGGING ***')
            import smdebug.tensorflow as smd
            # This assumes that we specified debugger_hook_config
            callback = smd.KerasHook.create_from_json_file()
            print(callback)
            print('*** CALLBACK {} ***'.format(callback))
            callbacks.append(callback)
            optimizer = callback.wrap_optimizer(optimizer)

        callback = tf.keras.callbacks.TensorBoard(log_dir=tensorboard_logs_path)
        callbacks.append(callback)
            
        print('*** OPTIMIZER {} ***'.format(optimizer))
        
        loss = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True)
        metric = tf.keras.metrics.SparseCategoricalAccuracy('accuracy')

        model.compile(optimizer=optimizer, loss=loss, metrics=[metric])
        print('Trained model {}'.format(model))
        print(model.summary())

        if run_validation:
            validation_data_filenames = glob(os.path.join(validation_data, '*.tfrecord'))
            print('validation_data_filenames {}'.format(validation_data_filenames))
            validation_dataset = file_based_input_dataset_builder(
                channel='validation',
                input_filenames=validation_data_filenames,
                pipe_mode=pipe_mode,
                is_training=False,
                drop_remainder=False,
                batch_size=validation_batch_size,
                epochs=epochs,
                steps_per_epoch=validation_steps,
                max_seq_length=max_seq_length).map(select_data_and_label_from_record)
            
            # HACK:  trim the Validation dataset down to equal the number of validation steps to workaround PipeMode issue
            validation_dataset = validation_dataset.take(validation_steps)
            
            train_and_validation_history = model.fit(train_dataset,
                                                     shuffle=True,
                                                     epochs=epochs,
                                                     steps_per_epoch=train_steps_per_epoch,
                                                     validation_data=validation_dataset,
                                                     validation_steps=validation_steps,
                                                     callbacks=callbacks)
            print(train_and_validation_history)
        else: # Not running validation
            train_history = model.fit(train_dataset,
                                      shuffle=True,
                                      epochs=epochs,
                                      steps_per_epoch=train_steps_per_epoch,
                                      callbacks=callbacks)
            print(train_history)

        if run_test:
            test_data_filenames = glob(os.path.join(test_data, '*.tfrecord'))
            print('test_data_filenames {}'.format(test_data_filenames))
            test_dataset = file_based_input_dataset_builder(
                channel='test',
                input_filenames=test_data_filenames,
                pipe_mode=pipe_mode,
                is_training=False,
                drop_remainder=False,
                batch_size=test_batch_size,
                epochs=epochs,
                steps_per_epoch=test_steps,
                max_seq_length=max_seq_length).map(select_data_and_label_from_record)

            test_history = model.evaluate(test_dataset,
                                          steps=test_steps,
                                          callbacks=callbacks)
            print(test_history)

            
        # Save the fine-tuned Transformers Model
        print('transformer_fine_tuned_model_path {}'.format(transformer_fine_tuned_model_path))   

        model.save_pretrained(transformer_fine_tuned_model_path)

        # Save the TensorFlow SavedModel
        print('tensorflow_saved_model_path {}'.format(tensorflow_saved_model_path))   
        model.save(tensorflow_saved_model_path, save_format='tf')

    if run_sample_predictions:
        loaded_model = TFDistilBertForSequenceClassification.from_pretrained(transformer_fine_tuned_model_path,
                                                                       id2label={
                                                                        0: 1,
                                                                        1: 2,
                                                                        2: 3,
                                                                        3: 4,
                                                                        4: 5
                                                                       },
                                                                       label2id={
                                                                        1: 0,
                                                                        2: 1,
                                                                        3: 2,
                                                                        4: 3,
                                                                        5: 4
                                                                       })

        tokenizer = DistilBertTokenizer.from_pretrained('distilbert-base-uncased')

        if num_gpus >= 1:
            inference_device = 0 # GPU 0
        else:
            inference_device = -1 # CPU
        print('inference_device {}'.format(inference_device))

        inference_pipeline = TextClassificationPipeline(model=loaded_model, 
                                                        tokenizer=tokenizer,
                                                        framework='tf',
                                                        device=inference_device)  

        print("""I loved it!  I will recommend this to everyone.""", inference_pipeline("""I loved it!  I will recommend this to everyone."""))
        print("""It's OK.""", inference_pipeline("""It's OK."""))
        print("""Really bad.  I hope they don't make this anymore.""", inference_pipeline("""Really bad.  I hope they don't make this anymore."""))
