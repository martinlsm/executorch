# Copyright (c) Qualcomm Innovation Center, Inc.
# All rights reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from typing import Dict

import executorch.backends.qualcomm.python.PyQnnWrapperAdaptor as PyQnnWrapper

import torch
from executorch.backends.qualcomm.utils.constants import (
    QCOM_QUANT_ATTRS,
    QCOM_SCALES,
    QCOM_ZERO_POINTS,
)

from .node_visitor import NodeVisitor
from .node_visitor_manager import register_node_visitor
from .qnn_constants import OpFullyConnected, QNN_OP_PACKAGE_NAME_QTI_AISW
from .utils import get_parameter


@register_node_visitor
class LinearVisitor(NodeVisitor):
    target = ["aten.linear.default"]

    def __init__(self, *args) -> None:
        super().__init__(*args)

    def define_node(
        self,
        node: torch.fx.Node,
        nodes_to_wrappers: Dict[torch.fx.Node, PyQnnWrapper.TensorWrapper],
    ) -> PyQnnWrapper.PyQnnOpWrapper:
        linear_input_tensors = []
        input_node = self.get_node(node.args[0])
        input_tensor = self.get_tensor(input_node, node)
        input_tensor_wrapper = self.define_tensor(
            input_node,
            node,
            input_tensor,
            PyQnnWrapper.Qnn_TensorType_t.QNN_TENSOR_TYPE_NATIVE,
            nodes_to_wrappers,
        )
        linear_input_tensors.append(input_tensor_wrapper)

        weight_node = self.get_node(node.args[1])
        if (
            quant_attrs := weight_node.meta.get(QCOM_QUANT_ATTRS)
        ) and QCOM_SCALES in quant_attrs:
            # Dimension of weight is [m, n], per channel quant params is [m]
            # Change to [m, 1] to fit the tensor.div(s).add(z)
            quant_attrs[QCOM_SCALES] = quant_attrs[QCOM_SCALES].reshape([-1, 1])
            quant_attrs[QCOM_ZERO_POINTS] = quant_attrs[QCOM_ZERO_POINTS].reshape(
                [-1, 1]
            )

        weight_tensor = get_parameter(weight_node, self.edge_program)
        weight_tensor_wrapper = self.define_tensor(
            weight_node,
            node,
            weight_tensor,
            PyQnnWrapper.Qnn_TensorType_t.QNN_TENSOR_TYPE_STATIC,
            nodes_to_wrappers,
        )
        linear_input_tensors.append(weight_tensor_wrapper)

        if len(node.args) >= 3:
            bias_node = self.get_node(node.args[2])

            bias_tensor_type = PyQnnWrapper.Qnn_TensorType_t.QNN_TENSOR_TYPE_STATIC
            bias_tensor = get_parameter(bias_node, self.edge_program)
            # if bias_node is getitem
            if bias_tensor is None:
                bias_tensor_type = PyQnnWrapper.Qnn_TensorType_t.QNN_TENSOR_TYPE_NATIVE
                bias_tensor = bias_node.meta["val"]

            bias_tensor_wrapper = self.define_tensor(
                bias_node,
                node,
                bias_tensor,
                bias_tensor_type,
                nodes_to_wrappers,
            )
            linear_input_tensors.append(bias_tensor_wrapper)

        output_tensor = self.get_tensor(node, node)
        output_tensor_wrapper = self.define_tensor(
            node,
            node,
            output_tensor,
            PyQnnWrapper.Qnn_TensorType_t.QNN_TENSOR_TYPE_NATIVE,
            nodes_to_wrappers,
        )

        linear_op = PyQnnWrapper.PyQnnOpWrapper(
            node.name,
            QNN_OP_PACKAGE_NAME_QTI_AISW,
            OpFullyConnected.op_name,
        )
        linear_op.AddInputTensors(linear_input_tensors)
        linear_op.AddOutputTensors([output_tensor_wrapper])

        return linear_op
