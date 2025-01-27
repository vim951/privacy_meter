# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# pylint: skip-file
# pyformat: disable

# Modification by yuan74: 
# add sys argument to set logdir
# import pandas to save the fpr tpr in csv files
# change from using os.walk(p) to using sorted(os.listdir(os.path.join(p))): to ensure that we are attacking the last target model in a directory

import sys
import pandas as pd


import os
import scipy.stats

import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import auc, roc_curve
import functools

# Look at me being proactive!
import matplotlib
matplotlib.rcParams['pdf.fonttype'] = 42
matplotlib.rcParams['ps.fonttype'] = 42


def sweep(score, x):
    """
    Compute a ROC curve and then return the FPR, TPR, AUC, and ACC.
    """
    fpr, tpr, _ = roc_curve(x, -score)
    acc = np.max(1-(fpr+(1-tpr))/2)
    return fpr, tpr, auc(fpr, tpr), acc

def load_data(p):
    """
    Load our saved scores and then put them into a big matrix.
    """
    global scores, keep
    scores = []
    keep = []

    for f in sorted(os.listdir(os.path.join(p))):
        print(f)
        if not f.startswith("experiment"): continue
        if not os.path.exists(os.path.join(p, f, "scores")): continue
        last_epoch = sorted(os.listdir(os.path.join(p, f, "scores")))
        if len(last_epoch) == 0: continue
        filepath = os.path.join(p, f, "scores", last_epoch[-1])
        print(f"loading scores from: {filepath}")
        scores_f = np.load(os.path.join(p, f, "scores", last_epoch[-1])) 
        print(f"Does this have nan values: {np.count_nonzero(np.isnan(scores_f))}")
        scores.append(scores_f)
        keep_f = np.load(os.path.join(p, f, "keep.npy"))
        print(f"Number of values to keep: {np.sum(keep_f)}")
        keep.append(keep_f)

    scores = np.array(scores)
    keep = np.array(keep)[:, :scores.shape[1]]

    return scores, keep


def generate_ours(keep, scores, check_keep, check_scores, in_size=100000, out_size=100000,
                  fix_variance=False):
    """
    Fit a two predictive models using keep and scores in order to predict
    if the examples in check_scores were training data or not, using the
    ground truth answer from check_keep.
    """
    print(scores.shape)

    dat_in = []
    dat_out = []

    for j in range(scores.shape[1]):
        dat_in.append(scores[keep[:, j], j, :])
        dat_out.append(scores[~keep[:, j], j, :])

    in_size = min(min(map(len, dat_in)), in_size)
    out_size = min(min(map(len, dat_out)), out_size)

    dat_in = np.array([x[:in_size] for x in dat_in])
    dat_out = np.array([x[:out_size] for x in dat_out])

    mean_in = np.median(dat_in, 1)
    mean_out = np.median(dat_out, 1)

    if fix_variance:
        std_in = np.std(dat_in)
        std_out = np.std(dat_in)
    else:
        std_in = np.std(dat_in, 1)
        std_out = np.std(dat_out, 1)

    prediction = []
    answers = []
    for ans, sc in zip(check_keep, check_scores):
        pr_in = -scipy.stats.norm.logpdf(sc, mean_in, std_in + 1e-30)
        pr_out = -scipy.stats.norm.logpdf(sc, mean_out, std_out + 1e-30)
        score = pr_in - pr_out

        prediction.extend(score.mean(1))
        answers.extend(ans)

    return prediction, answers


def generate_ours_offline(keep, scores, check_keep, check_scores, in_size=100000, out_size=100000,
                          fix_variance=False):
    """
    Fit a single predictive model using keep and scores in order to predict
    if the examples in check_scores were training data or not, using the
    ground truth answer from check_keep.
    """
    dat_in = []
    dat_out = []

    for j in range(scores.shape[1]):
        dat_in.append(scores[keep[:, j], j, :])
        dat_out.append(scores[~keep[:, j], j, :])

    out_size = min(min(map(len, dat_out)), out_size)

    dat_out = np.array([x[:out_size] for x in dat_out])

    mean_out = np.median(dat_out, 1)

    if fix_variance:
        std_out = np.std(dat_out)
    else:
        std_out = np.std(dat_out, 1)

    prediction = []
    answers = []
    for ans, sc in zip(check_keep, check_scores):
        score = scipy.stats.norm.logpdf(sc, mean_out, std_out + 1e-30)

        prediction.extend(score.mean(1))
        answers.extend(ans)
    return prediction, answers


def generate_global(keep, scores, check_keep, check_scores):
    """
    Use a simple global threshold sweep to predict if the examples in
    check_scores were training data or not, using the ground truth answer from
    check_keep.
    """
    prediction = []
    answers = []
    for ans, sc in zip(check_keep, check_scores):
        prediction.extend(-sc.mean(1))
        answers.extend(ans)

    return prediction, answers


def do_plot(fn, keep, scores, ntest, legend='', metric='auc', sweep_fn=sweep, **plot_kwargs):
    """
    Generate the ROC curves by using ntest models as test models and the rest to train.
    """

    prediction, answers = fn(keep[:-ntest],
                             scores[:-ntest],
                             keep[-ntest:],
                             scores[-ntest:])

    fpr, tpr, auc, acc = sweep_fn(np.array(prediction), np.array(answers, dtype=bool))

    low = tpr[np.where(fpr < .001)[0][-1]]

    print('Attack %s   AUC %.4f, Accuracy %.4f, TPR@0.1%%FPR of %.4f' % (legend, auc, acc, low))

    metric_text = ''
    if metric == 'auc':
        metric_text = 'auc=%.3f' % auc
    elif metric == 'acc':
        metric_text = 'acc=%.3f' % acc

    plt.plot(fpr, tpr, label=legend + metric_text, **plot_kwargs)
    df = pd.DataFrame(data={
        'fpr': fpr,
        'tpr': tpr
    })
    filepath = f"./{logdir}_tmp/{legend}_fpr_tpr_data.csv"
    df.to_csv(filepath)
    return (acc, auc)


def fig_fpr_tpr():

    if not os.path.exists(logdir + "_tmp"): 
        os.mkdir(logdir + "_tmp")

    plt.figure(figsize=(4, 3))

    do_plot(generate_ours,
            keep, scores, 1,
            "online",
            metric='auc'
            )

    do_plot(functools.partial(generate_ours, fix_variance=True),
            keep, scores, 1,
            "online_fixed_variance",
            metric='auc'
            )

    do_plot(functools.partial(generate_ours_offline),
            keep, scores, 1,
            "offline",
            metric='auc'
            )

    do_plot(functools.partial(generate_ours_offline, fix_variance=True),
            keep, scores, 1,
            "offline_fixed_variance",
            metric='auc'
            )

    do_plot(generate_global,
            keep, scores, 1,
            "global_threshold",
            metric='auc'
            )

    plt.semilogx()
    plt.semilogy()
    plt.xlim(1e-5, 1)
    plt.ylim(1e-5, 1)
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.plot([0, 1], [0, 1], ls='--', color='gray')
    plt.subplots_adjust(bottom=.18, left=.18, top=.96, right=.96)
    plt.legend(fontsize=8)
    plt.savefig(logdir+"_tmp/fprtpr.png")
    plt.show()

logdir = sys.argv[1]
load_data(logdir)
fig_fpr_tpr()
