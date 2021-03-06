import os
import sys
import argparse
import time
import numpy as np

from keras.models import load_model
from common import LookupTable
from misc_utils import Flush
from train_model import load_data_new, Graph, data_process, _tqdm

#
import tensorflow as tf
import keras.backend.tensorflow_backend as KTF


def get_session(gpu_fraction=0.05):
    num_threads = os.environ.get('OMP_NUM_THREADS')
    gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=gpu_fraction)
    if num_threads:
        return tf.Session(config=tf.ConfigProto(gpu_options=tpu_options, intra_op_parallelism_threads=num_threads))
    else:
        return tf.Session(config=tf.ConfigProto(gpu_options=gpu_options))


#

NAME = 'RV4'
parser = argparse.ArgumentParser(prog=NAME)
parser.add_argument('-data', type=int, default=1, help='source of data')
parser.add_argument('-redirect', type=int, choices=(0, 1), default=0, help='redirect stdout to logfile')
args = parser.parse_args()
print('params:', args)
logfile = None
stdout_bak = sys.stdout


def make_test_data(ntable, routes_test, max_inter_capacity_size_test, maxlen_que, maxlen_ans, features,
                   max_intra_capacity_size_test):
    print('creating testing dataset ...')
    n_samples = len(routes_test)
    cap_test = np.zeros((n_samples, max_inter_capacity_size_test), dtype=np.int8)
    que_test = np.zeros((n_samples, maxlen_que, features), dtype=np.int8)
    ans_test = np.zeros((n_samples, maxlen_ans, features), dtype=np.int8)
    hid_test = np.zeros((n_samples, max_intra_capacity_size_test), dtype=np.int8)

    for i, route_test in _tqdm(enumerate(routes_test), desc='encoding'):
        cap_test[i] = route_test.inter_capacity
        que_test[i] = ntable.encode([route_test.index_path[0], route_test.index_path[-1]], maxlen_que)
        ans_test[i] = ntable.encode(route_test.index_path[1:-1], maxlen_ans)  # answer must be encoded!
        hid_test[i] = route_test.intra_capacity

    print('testing data shape:')
    print(' - inter-capacity:', cap_test.shape)
    print(' - question:', que_test.shape)
    print(' - answer:', ans_test.shape)

    # shuffle data before train/test split
    indices = np.arange(n_samples)
    np.random.shuffle(indices)
    cap_test = cap_test[indices]
    que_test = que_test[indices]
    ans_test = ans_test[indices]
    hid_test = hid_test[indices]

    return cap_test, que_test, ans_test, hid_test


def overlap_cancellation(path):
    cancel_path = path
    for src, dst in zip(path[:-1], path[1:]):
        if src == dst:
            cancel_path.remove(src)
    return cancel_path


_DATA_DIR = os.path.join(os.path.expanduser('~/Zhong_Exp/Datasets/routing'), 'data-{}'.format(args.data))
_MODELS_DIR = os.path.join(os.path.expanduser('~/Zhong_Exp/Datasets/routing'), 'models-{}'.format(args.data))
_STATICLOGS_DIR = os.path.join(os.path.expanduser('~/Zhong_Exp/Datasets/routing'), 'test-logs-{}'.format(args.data))

print('\n===== static test =====')
KTF.set_session(get_session())
_LOAD_DIRECT_MODEL = 'load_direct_model.txt'
_LOAD_DIRECT_TEST = 'load_direct_test.txt'
_LOAD_DIRECT_PATH = os.path.join(_DATA_DIR, _LOAD_DIRECT_MODEL)
_LOAD_DIRECT_PATH_TEST = os.path.join(_DATA_DIR, _LOAD_DIRECT_TEST)
model_load_lines = []
test_load_lines = []
with open(_LOAD_DIRECT_PATH, 'r', encoding='gb2312') as fr:
    for load_line in _tqdm(fr, desc='loading'):
        load_line = load_line.strip()
        model_load_lines.append(load_line)

with open(_LOAD_DIRECT_PATH_TEST, 'r', encoding='gb2312') as fr:
    for load_line in _tqdm(fr, desc='loading'):
        load_line = load_line.strip()
        test_load_lines.append(load_line)

graph = Graph(topo_file='topo9.yaml')

for load_train in model_load_lines:
    load_name = 'Req2Route' + load_train + '.h5'
    model_name = os.path.join(_MODELS_DIR, load_name)
    print('\nloading trained model' + model_name + '...')
    model = load_model(model_name)
    for load_test in test_load_lines:

        print('load_train, load_test', load_train[1:3], load_test[1:3])

        if load_test[1:3] == load_train[1:3]:
            continue

        print('testing trained model of' + load_train + 'on' + load_test)
        count_all, count_good, count_match, count_ignore = 0, 0, 0, 0

        _DATA_FILE_NAME = 'output_BRPC' + load_test + '.dat'
        DATA_FILE_PATH = os.path.join(_DATA_DIR, _DATA_FILE_NAME)
        PKL_FILE_PATH = DATA_FILE_PATH.replace('.dat', '.pkl')

        if args.redirect:
            try:
                logfile_name = 'train' + load_train + '_test' + load_test + '-static-print.log'
                whole_logfile = os.path.join(_STATICLOGS_DIR, logfile_name)
                print('static running stdout messages will be saved in', logfile_name)
                logfile = open(whole_logfile, 'w', encoding='utf8')
                sys.stdout = Flush(logfile)
            except:
                print('create logfile fail, use stdout instead', file=sys.stderr)

        routes, routes_test, min_node_index, max_node_index, min_node_test_index, max_node_test_index = load_data_new(
            DATA_FILE_PATH, PKL_FILE_PATH, from_pkl=True, save_pkl=False)
        has_congestion, congestion_node, max_inter_capacity_size, has_congestion_test, congestion_node_test, max_inter_capacity_size_test, max_intra_capacity_size_test = data_process(
            routes, routes_test, min_node_index, max_node_index, min_node_test_index, max_node_test_index)

        NODES = max_node_index if not has_congestion else congestion_node
        ntable = LookupTable(NODES)
        maxlen_1 = int(np.max([len(route.index_path) for route in routes]))  # longest path length in dataset
        maxlen_2 = int(
            np.max([len(route_test.index_path) for route_test in routes_test]))  # longest path length in dataset
        if maxlen_1 > maxlen_2:
            maxlen = maxlen_1
        else:
            maxlen = maxlen_2
        print(' - longest path of train and test:', maxlen)
        maxlen_que = 2  # <src> and <dest>
        maxlen_ans = maxlen - maxlen_que  # intermediate nodes in path (answer)
        features = NODES + 1  # add 0 as <padding>

        cap_test, que_test, ans_test, hid_test = make_test_data(ntable, routes_test, max_inter_capacity_size_test,
                                                                maxlen_que, maxlen_ans, features,
                                                                max_intra_capacity_size_test)

        staticlog = 'train' + load_train + 'test' + load_test + '-static.log'
        wholestaticlog = os.path.join(_STATICLOGS_DIR, staticlog)
        with open(wholestaticlog, 'w', encoding='utf8') as fw:
            for cap_sample, que_sample, ans_sample, hid_sample in _tqdm(zip(cap_test, que_test, ans_test, hid_test),
                                                                        desc='static'):
                count_all += 1

                pred_probs = model.predict(x=[cap_sample[np.newaxis, :], que_sample[np.newaxis, :]])
                pred_ans_seq = [x for x in graph.seq_before_zero(pred_probs.argmax(axis=-1)[0])]
                pred_ans_seq_index = [x - 1 for x in pred_ans_seq]

                que_sample = [x for x in graph.seq_before_zero(que_sample.argmax(axis=-1))]
                que_sample_index = [x - 1 for x in que_sample]

                ans_sample = [x for x in graph.seq_before_zero(ans_sample.argmax(axis=-1))]
                ans_sample_index = [x - 1 for x in ans_sample]

                real = [que_sample_index[0]] + ans_sample_index + [que_sample_index[1]]
                pred_path_index_ovp = [que_sample_index[0]] + pred_ans_seq_index + [que_sample_index[1]]

                pred_path_index = overlap_cancellation(pred_path_index_ovp)

                graph.reset_capacity()
                
                graph.set_capacity(caps=cap_sample, hidden_caps=hid_sample) 
               
                # metric 1: match (same route)
                count_match += (real == pred_path_index)
                incre_match = (real == pred_path_index)
                
                # metric 2: good path
                if 61 in pred_path_index:  # pred no path, real -1, see if match
                    count_good += (real == pred_path_index)
                    incre_good = (real == pred_path_index)
                else:  # pred a path
                    success, success_path = graph.is_buildable(pred_path_index, verbose=True)
                    count_good += success
                    incre_good = success
                if incre_match > incre_good:
                    print('Error', file=fw, flush=True)
                    print('Error on {} {}'.format(count_good, count_match))
                print('{}, {}, {}: {}, {}, {}'.format(count_good, count_match, que_sample, success, real,
                                                      pred_path_index), file=fw, flush=True)
        print('=' * 30)
        print('\nfinal results of static check:')
        useful = count_all - count_ignore
        print('* count_all:', count_all)
        print('* count_good: {}/{} ({:.4f})'.format(count_good, useful, count_good / useful))
        print('* count_match: {}/{} ({:.4f})'.format(count_match, useful, count_match / useful))

        # restore stdout
        if args.redirect:
            try:
                logfile.close()
                sys.stdout = stdout_bak
            except:
                print('logfile close fail', file=sys.stderr)
