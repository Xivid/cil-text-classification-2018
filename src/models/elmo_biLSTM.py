from core import BaseModel
from datasources import RawText
import os
import time
import datetime
import tensorflow as tf
import tensorflow_hub as hub
import numpy as np
from gensim.models import KeyedVectors
from utils.io import file_type
import logging

logger = logging.getLogger("ELMoBiLSTM")

class ELMoBiLSTM(BaseModel):
    predictions = list()

    def init(self):
        if not isinstance(self.data_source, RawText):
            logger.error("Only the RawText data source is supported!")
            exit()
        if self.data_source.embedding_src == "":
            logger.error("This model uses pre-trained word2vec embeddings, please provide the path to the embeddings.")
            exit()

    def train(self):
        logger.info("Training ELMoBiLSTM model...")
        out_dir = self.output_dir

        # load data from data source
        X = self.data_source.X
        Y = self.data_source.Y
        testX = self.data_source.testX
        max_tok_count = self.data_source.max_tok_count
        Y = np.array([[1, 0] if i == 1 else [0, 1] for i in Y], dtype=np.float32)

        logger.info("Loading ELMO module...")
        elmo = hub.Module("https://tfhub.dev/google/elmo/2", trainable=True)

        logger.info("Loading word2vec embeddings...")
        embedding_src = self.data_source.embedding_src
        is_binary = file_type(embedding_src)
        embedding = KeyedVectors.load_word2vec_format(embedding_src, binary=is_binary)

        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        def text2array(X):
            # ret = np.zeros((len(X), max_tok, 1024), dtype=np.float32)
            seq_len = np.zeros(len(X), dtype=np.int32)
            ret = np.array(X)
            for i, line in enumerate(X):
                seq_len[i] = len(line.split())
            return ret, seq_len

        def text2vecs(X, max_tok, embedding):
            max_tok = 0
            for line in X:
                max_tok = max(len(line.split()), max_tok)

            ret = np.zeros((len(X), max_tok, embedding.vector_size), dtype=np.float32)
            # seq_len = np.zeros(len(X), dtype=np.int32)
            for i, line in enumerate(X):
                tokens = line.split()
                # seq_len[i] = len(tokens)
                for j, token in enumerate(tokens):
                    if token in embedding.vocab:
                        ret[i][j] = embedding[token]
            return ret  # , seq_len

        def batch_gen(X, Y, batch_size, n_epochs, embedding, max_tok):
            n_sample = len(X)
            batches_per_epoch = int(np.ceil(n_sample / batch_size))

            for epoch in range(n_epochs):
                shuffled_idx = np.random.permutation(np.arange(n_sample))
                shuffled_X = [X[i] for i in shuffled_idx]
                shuffled_Y = Y[shuffled_idx]

                start_idx = 0
                for batch in range(batches_per_epoch):
                    end_idx = min(start_idx + batch_size, n_sample)
                    vecX, seq_len = text2array(shuffled_X[start_idx:end_idx])
                    Y_batch = shuffled_Y[start_idx:end_idx]

                    yield vecX, Y_batch, seq_len
                    start_idx += batch_size


        class EbiLSTMModel():
            def __init__(self, embedding_dim, max_tok, num_cell=512):
                self.X = tf.placeholder(tf.string, [None], name="X")
                self.X_vecs = tf.placeholder(tf.float32, [None, None, embedding_dim], name="X_vecs")
                self.seq_len = tf.placeholder(tf.int32, [None], name="seq_len")
                self.Y = tf.placeholder(tf.float32, [None, 2], name="Y")

                elmo_space = elmo(self.X, signature='default', as_dict=True)['elmo']
                elmo_space = tf.layers.dropout(elmo_space, rate=0.4)
                # _, elmo_seq_len, _ = context_vecs.get_shape().as_list()
                # pad_elmo = tf.constant([[0, 0], [0, max_tok - elmo_seq_len], [0, 0]])
                # elmo_space = tf.pad(context_vecs, pad_elmo)

                elmo_word_vecs = tf.concat([self.X_vecs, elmo_space], 2)

                # Configure forward and backward LSTM cells
                fw_lstm_cells = tf.nn.rnn_cell.LSTMCell(num_cell)
                bw_lstm_celss = tf.nn.rnn_cell.LSTMCell(num_cell)

                ((outputs_fw, outputs_bw), (outputs_state_fw, outputs_state_bw)) = tf.nn.bidirectional_dynamic_rnn(
                    cell_fw=fw_lstm_cells,
                    cell_bw=bw_lstm_celss,
                    inputs=elmo_word_vecs,
                    dtype=tf.float32,
                    sequence_length=self.seq_len,
                )

                # compute the final outputs and final states by combining forward and backward results
                outputs = tf.concat((outputs_fw, outputs_bw), 2)

                final_state_c = tf.concat((outputs_state_fw.c, outputs_state_bw.c), 1)
                final_state_h = tf.concat((outputs_state_fw.h, outputs_state_bw.h), 1)
                outputs_final_state = tf.contrib.rnn.LSTMStateTuple(c=final_state_c,
                                                                    h=final_state_h)

                final_output = tf.layers.dropout(outputs_final_state.h, rate=0.2)

                # Outputs
                with tf.name_scope("output"):
                    # hidden_dense = tf.layers.dense(final_output, units=128, activation=tf.nn.relu)
                    # hidden_dense = tf.layers.dropout(hidden_dense, rate=0.5)
                    self.score = tf.layers.dense(final_output, units=2, activation=tf.nn.relu)
                    self.predictions = tf.nn.softmax(self.score, name='predictions')
                    self.class_prediction = tf.argmax(self.predictions, 1)

                with tf.name_scope("loss"):
                    self.losses = tf.nn.softmax_cross_entropy_with_logits_v2(logits=self.score, labels=self.Y)
                    self.loss = tf.reduce_mean(self.losses, name='loss')
                with tf.name_scope("accuracy"):
                    self.correct_pred = tf.equal(tf.argmax(self.predictions, 1), tf.argmax(self.Y, 1))
                    self.accuracy = tf.reduce_mean(tf.cast(self.correct_pred, "float"), name="accuracy")


        # Hyperperameters for training
        val_samples = 10000
        val_split = 50
        n_epochs = 20
        batch_size = 32
        learning_rate = 1e-4
        eval_every_step = 2000
        output_every_step = 100
        checkpoint_every_step = 2000

        # Model Parameters
        embedding_dim = embedding.vector_size
        num_cell = 512  # <- cell size of biLSTM

        # Split into training and validation
        logger.info("Splitting dataset into training and validation...")
        shuffled_idx = np.random.permutation(np.arange(len(X)))
        shuffled_X = [X[i] for i in shuffled_idx]
        shuffled_Y = Y[shuffled_idx]

        val_X = [shuffled_X[i:min(i + val_split, val_samples)] for i in range(0, val_samples, val_split)]
        val_Y = np.split(shuffled_Y[:val_samples], val_samples / val_split)
        train_X = shuffled_X[val_samples:]
        train_Y = shuffled_Y[val_samples:]

        # RNN
        logger.info("Building model...")
        session_conf = tf.ConfigProto(
            allow_soft_placement=True,
            log_device_placement=False)
        sess = tf.Session(config=session_conf)

        model = EbiLSTMModel(embedding_dim, max_tok_count, num_cell)

        global_step = tf.Variable(1, name="global_step", trainable=False)
        # learning_rate = tf.train.exponential_decay(1e-5,
        #                                           global_step=global_step,
        #                                           decay_steps=2000,
        #                                           decay_rate=0.97,
        #                                           staircase=False)
        optimizer = tf.train.AdamOptimizer(learning_rate)

        # Gradient clipping
        # gvs = optimizer.compute_gradients(model.loss)
        # capped_gvs = [(tf.clip_by_value(grad, -5., 5.), var) for grad, var in gvs]
        # train_op = optimizer.apply_gradients(capped_gvs, global_step=global_step)
        train_op = optimizer.minimize(model.loss, global_step=global_step)
        # 'compute_gradients' returns a list of (gradient, variable) pairs.

        # Summary
        out_dir_full = os.path.abspath(os.path.join(out_dir, 'runs'))
        if not os.path.exists(out_dir_full):
            os.makedirs(out_dir_full)
        # Summaries for loss and accuracy
        loss_summary = tf.summary.scalar("loss", model.loss)
        acc_summary = tf.summary.scalar("accuracy", model.accuracy)

        # Train Summaries
        train_summary_op = tf.summary.merge([loss_summary, acc_summary])
        train_summary_dir = os.path.join(out_dir_full, "summaries", "train")
        train_summary_writer = tf.summary.FileWriter(train_summary_dir, sess.graph)

        # Validation summaries
        val_avg_acc = tf.placeholder(tf.float32, name='val_avg_acc')
        val_std_acc = tf.placeholder(tf.float32, name='val_std_acc')
        val_avg_loss = tf.placeholder(tf.float32, name='val_avg_loss')
        val_summary_op = tf.summary.merge([tf.summary.scalar('val_accuracy', val_avg_acc),
                                           tf.summary.scalar('val_std_accuracy', val_std_acc),
                                           tf.summary.scalar('val_loss', val_avg_loss)])
        val_summary_dir = os.path.join(out_dir_full, "summaries", "dev")
        val_summary_writer = tf.summary.FileWriter(val_summary_dir, sess.graph)

        # Checkpoint directory. Tensorflow assumes this directory already exists so we need to create it
        checkpoint_dir = os.path.abspath(os.path.join(out_dir_full, "checkpoints"))
        checkpoint_prefix = os.path.join(checkpoint_dir, "model")
        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)
        saver = tf.train.Saver(tf.global_variables())

        # Initialize all variables
        logger.info("Initializing model variables...")
        sess.run(tf.global_variables_initializer())


        def train_step(x_batch, y_batch, seq_len):
            """A single training step"""
            x_vecs = text2vecs(x_batch, max_tok_count, embedding)
            feed_dict = {
                model.X: x_batch,
                model.X_vecs: x_vecs,
                model.Y: y_batch,
                model.seq_len: seq_len
            }
            # add grad_summaries_merged to keep track of gradient values (time intense!)
            _, step, summaries, train_loss, train_accuracy = sess.run(
                [train_op, global_step, train_summary_op, model.loss, model.accuracy],
                feed_dict)
            train_summary_writer.add_summary(summaries, step)
            return train_loss, train_accuracy


        def val_step(x_batch, y_batch):
            """Performs a model evaluation batch step on the dev set."""
            x_array, seq_len = text2array(x_batch)
            x_vecs = text2vecs(x_batch, max_tok_count, embedding)
            feed_dict = {
                model.X: x_array,
                model.X_vecs: x_vecs,
                model.Y: y_batch,
                model.seq_len: seq_len
            }
            _, val_loss, val_accuracy = sess.run(
                [global_step, model.loss, model.accuracy], feed_dict)
            return val_loss, val_accuracy


        def evaluate_model(current_step):
            """Evaluates model on a dev set."""
            losses = np.zeros(len(val_X))
            accuracies = np.zeros(len(val_X))

            for i in range(len(val_X)):
                loss, accuracy = val_step(val_X[i], val_Y[i])
                losses[i] = loss
                accuracies[i] = accuracy

            average_loss = np.nanmean(losses)
            average_accuracy = np.nanmean(accuracies)
            std_accuracy = np.nanstd(accuracies)
            val_summary = sess.run(val_summary_op, feed_dict={val_avg_acc: average_accuracy,
                                                              val_std_acc: std_accuracy, val_avg_loss: average_loss})
            val_summary_writer.add_summary(val_summary, current_step)
            time_str = datetime.datetime.now().isoformat()
            logger.info("{}: Evaluation report at step {}:".format(time_str, current_step))
            logger.info("\tloss {:g}\n\tacc {:g} (stddev {:g})\n"
                   "\t(Tested on the full test set)\n"
                   .format(average_loss, average_accuracy, std_accuracy))
            return average_accuracy

        def predict_test(submission_file):
            self.predictions = []
            with open(submission_file, "w+") as f:
                f.write("Id,Prediction\n")
                testX_t = [testX[i:i + val_split] for i in range(0, len(testX), val_split)]
                sample_no = 1
                for testBatch in testX_t:
                    ret, seq_len = text2vecs(testBatch, max_tok_count, embedding)
                    feed_dict = {
                        model.X: ret,
                        model.seq_len: seq_len
                    }
                    predictions = sess.run(model.class_prediction, feed_dict)
                    for p in predictions:
                        self.predictions.append(p)
                        f.write("{},{}\n".format(sample_no, (1 if p == 0 else -1)))
                        sample_no += 1
            logger.info("saved to %s" % submission_file)
        logger.info("Generating batches...")
        batches = batch_gen(train_X, train_Y, batch_size, n_epochs, elmo, max_tok_count)

        # Training
        logger.info("Training started")
        current_step = None
        try:
            lcum = 0
            acum = 0
            best_accuracy = -1
            for batchX, batchY, seq_len in batches:
                l, a = train_step(batchX, batchY, seq_len)
                lcum += l
                acum += a
                current_step = tf.train.global_step(sess, global_step)

                if current_step % output_every_step == 0:
                    time_str = datetime.datetime.now().isoformat()
                    logger.info("{}: step {}, loss {:g}, acc {:g}".format(time_str, current_step, lcum / output_every_step,
                                                                     acum / output_every_step))
                    lcum = 0
                    acum = 0
                if current_step % eval_every_step == 0:
                    logger.info("\nEvaluating...")
                    eval_start_ms = int(time.time() * 1000)
                    current_accuracy = evaluate_model(current_step)
                    eval_time_ms = int(time.time() * 1000) - eval_start_ms
                    logger.info("Evaluation performed in {0}ms.".format(eval_time_ms))
                    if current_accuracy > best_accuracy:
                        # Evaluate test data
                        best_accuracy = current_accuracy
                        submission_file = "../output/models/EbiLSTM/kaggle_%s_accu%f.csv" % (
                        datetime.datetime.now().strftime("%Y%m%d%H%M%S"), best_accuracy)
                        logger.info("New best accuracy, generating submission file: %s" % submission_file)
                        predict_test(submission_file)

                if current_step % checkpoint_every_step == 0:
                    logger.info("Save model parameters...")
                    path = saver.save(sess, checkpoint_prefix, global_step=current_step)
                    logger.info("Saved model checkpoint to {}\n".format(path))

            if current_step is None:
                logger.info("No steps performed.")
            else:
                logger.info("\n\nFinished all batches. Performing final evaluations.")

            logger.info("Performing final evaluation...")
            evaluate_model(current_step)

            logger.info("Performing final checkpoint...")
            path = saver.save(sess, checkpoint_prefix, global_step=current_step)
            logger.info("Saved model checkpoint to {}\n".format(path))

            # Evaluate test data
            submission_file = out_dir + "kaggle_final_%s.csv" % datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            predict_test(submission_file)

        except KeyboardInterrupt:
            if current_step is None:
                logger.info("No checkpointing to do.")
            else:
                logger.info("Training interrupted. Performing final checkpoint.")
                logger.info("Press C-c again to forcefully interrupt this.")
                path = saver.save(sess, checkpoint_prefix, global_step=current_step)
                logger.info("Saved model checkpoint to {}\n".format(path))

    def predict(self, X):
        # prediciton already done during training with ensembling, just return the result
        return self.predictions