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
from treeano.sandbox.nodes import timesout
from treeano.sandbox.nodes import batch_normalization as bn
import canopy
import canopy.sandbox.datasets

fX = theano.config.floatX

# ############################### prepare data ###############################

train, valid, test = canopy.sandbox.datasets.mnist()

# ############################## prepare model ##############################

model = tn.HyperparameterNode(
    "model",
    tn.SequentialNode(
        "seq",
        [tn.InputNode("x", shape=(None, 1,  28, 28)),
         tn.DenseNode("fc1"),
         bn.BatchNormalizationNode("bn1"),
         # timesout.TimesoutNode("to1"),
         # timesout.DoubleTimesoutNode("to1"),
         # timesout.GeometricMeanOutNode("to1"),
         # timesout.BiasedTimesoutNode("to1"),
         # timesout.BiasedDoubleTimesoutNode("to1"),
         # tn.TanhNode("tanh1"),
         # timesout.IndexedTimesoutNode("to1"),
         timesout.IndexedGatedTimesoutNode("to1"),
         # tn.ReLUNode("relu1"),
         tn.DropoutNode("do1"),
         tn.DenseNode("fc2"),
         bn.BatchNormalizationNode("bn2"),
         # timesout.TimesoutNode("to2"),
         # timesout.DoubleTimesoutNode("to2"),
         # timesout.GeometricMeanOutNode("to2"),
         # timesout.BiasedTimesoutNode("to2"),
         # timesout.BiasedDoubleTimesoutNode("to2"),
         # tn.TanhNode("tanh2"),
         # timesout.IndexedTimesoutNode("to2"),
         timesout.IndexedGatedTimesoutNode("to2"),
         # tn.ReLUNode("relu2"),
         tn.DropoutNode("do2"),
         tn.DenseNode("fc3", num_units=10),
         tn.SoftmaxNode("pred"),
         ]),
    num_units=512,
    num_pieces=2,
    dropout_probability=0.5,
    inits=[treeano.inits.XavierNormalInit()],
)

with_updates = tn.HyperparameterNode(
    "with_updates",
    tn.AdamNode(
        "adam",
        {"subtree": model,
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
     canopy.handlers.chunk_variables(batch_size=BATCH_SIZE,
                                     variables=["x", "y"])],
    {"x": "x", "y": "y"},
    {"cost": "cost", "pred": "pred"})


def validate(in_dict, results_dict):
    valid_out = valid_fn(valid)
    probabilities = valid_out["pred"]
    predicted_classes = np.argmax(probabilities, axis=1)
    results_dict["valid_cost"] = valid_out["cost"]
    results_dict["valid_time"] = valid_out["valid_time"]
    results_dict["valid_accuracy"] = sklearn.metrics.accuracy_score(
        valid["y"], predicted_classes)

train_fn = canopy.handled_fn(
    network,
    [canopy.handlers.time_call(key="total_time"),
     canopy.handlers.call_after_every(1, validate),
     canopy.handlers.time_call(key="train_time"),
     canopy.handlers.chunk_variables(batch_size=BATCH_SIZE,
                                     variables=["x", "y"])],
    {"x": "x", "y": "y"},
    {"train_cost": "cost"},
    include_updates=True)


# ################################# training #################################

print("Starting training...")
canopy.evaluate_until(fn=train_fn,
                      gen=itertools.repeat(train),
                      max_iters=25)
