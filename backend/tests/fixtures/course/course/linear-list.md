# 线性表：接口与存储

原作：Pat Morin，Open Data Structures（in pseudocode）。
许可：[CC BY 2.5 CA](https://creativecommons.org/licenses/by/2.5/ca/)。
改动：知序项目中文整理，补充例子与复杂度计算条件；非逐字翻译。

## 线性序列

线性表表示有序的元素序列，通常从下标 0 开始。逻辑次序不要求元素在内存中相邻；顺序表和链表可实现相同的列表接口。空表的元素个数为 0。

## 顺序表

顺序表在数组中存储元素。给定有效下标，直接访问对应元素的时间为 O(1)。索引越界必须先处理。

在已有 n 个元素的固定数组中，向下标 i 插入一个元素，且容量足够、不发生扩容时，需要向后移动 n-i 个元素。表头插入移动 n 个，表尾插入移动 0 个。删除下标 i 后，后续元素向前移动 n-i-1 个。因此中间或表头的插入、删除最坏为 O(n)。

## 单链表

单链表节点包含数据和指向后继节点的 next 引用。非循环单链表的最后一个节点 next 为空。给定节点位置后，可通过连接调整完成局部操作；从头查找第 i 个节点需要逐节点移动，最坏 O(n)，不能把查找时间忽略。

在已知节点 p 后插入新节点 s，应先令 s.next 指向 p.next，再让 p.next 指向 s。这里只计算已有 p 和 s 时的链接调整，不包括查找或分配成本。

## 例子

序列 [10,20,30,40] 在下标 1 插入 15，结果为 [10,15,20,30,40]，移动原来的 20、30、40，共 3 个元素。

## 原始来源

- [列表接口](https://opendatastructures.org/ods-python/1_2_Interfaces.html)
- [数组列表概览](https://opendatastructures.org/ods-python/2_Array_Based_Lists.html)
- [ArrayStack 的按下标插入](https://opendatastructures.org/ods-python/2_1_ArrayStack_Fast_Stack_O.html)
- [链表概览](https://opendatastructures.org/ods-python/3_Linked_Lists.html)
- [单链表节点](https://opendatastructures.org/ods-python/3_1_SLList_Singly_Linked_Li.html)
