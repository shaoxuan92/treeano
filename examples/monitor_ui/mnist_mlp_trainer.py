from __future__ import division, absolute_import
from __future__ import print_function, unicode_literals

import itertools
import numpy as np
import sklearn.datasets
import sklearn.cross_validation
import sklearn.metrics
import theano
import theano.tensor as T
import treeano
import treeano.nodes as tn
import canopy

fX = theano.config.floatX

# ############################### prepare data ###############################

mnist = sklearn.datasets.fetch_mldata('MNIST original')
# theano has a constant float type that it uses (float32 for GPU)
# also rescaling to [0, 1] instead of [0, 255]
X = mnist['data'].astype(fX) / 255.0
y = mnist['target'].astype("int32")
X_train, X_valid, y_train, y_valid = sklearn.cross_validation.train_test_split(
    X, y, random_state=42)

# NOTE: limit to small training set for faster epochs
X_train = X_train[:500]
X_valid = X_valid[:500]
y_train = y_train[:500]
y_valid = y_valid[:500]

in_train = {"x": X_train, "y": y_train}
in_valid = {"x": X_valid, "y": y_valid}

# ############################## prepare model ##############################
# architecture:
# - fully connected 512 units
# - ReLU
# - 50% dropout
# - fully connected 512 units
# - ReLU
# - 50% dropout
# - fully connected 10 units
# - softmax

# - the batch size can be provided as `None` to make the network
#   work for multiple different batch sizes
from treeano.sandbox.nodes.monitor_update_ratio import MonitorUpdateRatioNode
model = tn.HyperparameterNode(
    "model",
    tn.SequentialNode(
        "seq",
        [tn.InputNode("x", shape=(None, 28 * 28)),
         tn.MonitorVarianceNode("mv0"),
         tn.DenseNode("fc1"),
         tn.MonitorVarianceNode("mv1"),
         tn.ReLUNode("relu1"),
         tn.DropoutNode("do1"),
         tn.DenseNode("fc2"),
         tn.MonitorVarianceNode("mv2"),
         tn.ReLUNode("relu2"),
         tn.DropoutNode("do2"),
         tn.DenseNode("fc3", num_units=10),
         tn.MonitorVarianceNode("mv3"),
         tn.SoftmaxNode("pred"),
         ]),
    num_units=512,
    dropout_probability=0.5,
    inits=[treeano.inits.XavierNormalInit()],
)

with_updates = tn.HyperparameterNode(
    "with_updates",
    tn.AdamNode(
        "adam",
        {"subtree": MonitorUpdateRatioNode("updateratio", model),
         "cost": tn.TotalCostNode("cost", {
             "pred": tn.ReferenceNode("pred_ref", reference="model"),
             "target": tn.InputNode("y", shape=(None,), dtype="int32")},
        )}),
    cost_function=treeano.utils.categorical_crossentropy_i32,
)
network = with_updates.network()
network.build()  # build eagerly to share weights

BATCH_SIZE = 500

valid_fn = canopy.handled_fn(
    network,
    [canopy.handlers.time_call(key="valid_time"),
     canopy.handlers.override_hyperparameters(dropout_probability=0),
     canopy.handlers.evaluate_monitoring_variables(fmt="valid_%s"),
     canopy.handlers.chunk_variables(batch_size=BATCH_SIZE,
                                     variables=["x", "y"])],
    {"x": "x", "y": "y"},
    {"cost": "cost", "pred": "pred"})


def validate(in_dict, results_dict):
    valid_out = valid_fn(in_valid)
    probabilities = valid_out["pred"]
    predicted_classes = np.argmax(probabilities, axis=1)
    results_dict["valid_cost"] = valid_out["cost"]
    results_dict["valid_time"] = valid_out["valid_time"]
    results_dict["valid_accuracy"] = sklearn.metrics.accuracy_score(
        y_valid, predicted_classes)

train_fn = canopy.handled_fn(
    network,
    [canopy.handlers.time_call(key="total_time"),
     canopy.handlers.call_after_every(1, validate),
     canopy.handlers.time_call(key="train_time"),
     canopy.handlers.evaluate_monitoring_variables(fmt="train_%s"),
     canopy.handlers.chunk_variables(batch_size=BATCH_SIZE,
                                     variables=["x", "y"])],
    {"x": "x", "y": "y"},
    {"train_cost": "cost"},
    include_updates=True)


# ################################# training #################################

import canopy.sandbox.monitor_ui
result_writer = canopy.sandbox.monitor_ui.ResultWriter(dirname="monitor_dir",
                                                       pattern="")

print("Starting training...")
canopy.evaluate_until(fn=train_fn,
                      gen=itertools.repeat(in_train),
                      max_iters=1000,
                      callback=result_writer.write)
