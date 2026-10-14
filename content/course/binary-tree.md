# 二叉树：结构与遍历

结构部分原作：Pat Morin，Open Data Structures（in pseudocode），[CC BY 2.5 CA](https://creativecommons.org/licenses/by/2.5/ca/)。
遍历部分依据：Cliff Shaffer / OpenDSA，Copyright (c) 2012-2020 by the OpenDSA Project Contributors，[MIT 许可](../licenses/opendsa-MIT.txt)。
改动：知序项目中文整理，补充自定义树例子和高度约定；非逐字翻译。

## 结构

本项目讨论有根、有序二叉树：每个节点最多有左、右两个孩子，左右位置有区别。没有孩子的节点称为叶子；根没有父节点。

节点深度按到根的边数计，根深度为 0。本笔记统一按边数计高度：空树高度 -1，叶子高度 0，非空节点高度为 1+max(左子树高度,右子树高度)。部分教材按层数计高度，应先明确约定。

## 三种深度优先遍历

- 先序：根 → 左子树 → 右子树。
- 中序：左子树 → 根 → 右子树。
- 后序：左子树 → 右子树 → 根。

对左右子树递归采用同一顺序，空子树直接返回；每个非空节点访问一次。遍历 n 个节点的时间为 O(n)，递归辅助栈空间与树高相关，最坏可为 O(n)。

## 项目例子

```text
       A
      / \
     B   C
    / \
   D   E
```

先序 A B D E C；中序 D B E A C；后序 D E B C A。
该树有 5 个节点，3 个叶子 D、E、C，根 A 的高度为 2。

## 层序与常见误解

层序逐层从左到右访问，通常借助 FIFO 队列。该例的层序为 A B C D E。

普通二叉树不保证中序结果按数值排序。二叉搜索树的排序性质需要额外条件；仅凭“二叉树”不能推出排序结果。

## 原始来源

- [有根、有序二叉树](https://opendatastructures.org/ods-python/6_Binary_Trees.html)
- [递归算法与层序](https://opendatastructures.org/ods-python/6_1_BinaryTree_Basic_Binary.html)
- [OpenDSA 遍历模块](https://github.com/OpenDSA/OpenDSA/blob/master/RST/en/Binary/BinaryTreeTraversal.rst)
