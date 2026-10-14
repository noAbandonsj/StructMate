# 栈与队列：次序和边界

原作：Pat Morin，Open Data Structures（in pseudocode）。
许可：[CC BY 2.5 CA](https://creativecommons.org/licenses/by/2.5/ca/)。
改动：知序项目中文整理，增加操作例子和“保留一个空位”的教学约定；非逐字翻译。

## 栈

栈遵循后进先出（LIFO）。push 将元素放到栈顶，pop 移除并返回栈顶。空栈不能正常执行 pop。

项目例子：从空栈依次 push(1)、push(2)、pop()、push(3)、pop()，两次弹出分别为 2、3，最后保留 [1]。顺序描述均为栈底到栈顶。

## 普通队列

普通队列遵循先进先出（FIFO）。enqueue 从队尾加入，dequeue 从队头移除；空队列不能正常出队。优先队列采用优先级规则，应与普通 FIFO 队列区分。

带 head 和 tail 的单链表可从尾部入队、从头部出队。数组队列可通过环形下标避免每次出队都移动全部元素。

## 循环队列教学约定

以下公式只适用于本项目固定容量、保留一个空位的实现：数组容量 N>=2，front 指向下一次出队位置，rear 指向下一次入队位置。

- 队空：front == rear。
- 队满：(rear+1) % N == front。
- 实际最多保存 N-1 个元素。
- 当前长度：(rear-front+N) % N。
- 入队后 rear=(rear+1)%N；出队后 front=(front+1)%N。

这是项目采用的教学约定。Open Data Structures 的 ArrayQueue 用单独的元素计数并可扩容；不能把本节的空位公式无条件套到那种实现。

## 例子

N=8、front=6、rear=2 时，当前长度为 (2-6+8)%8=4。有效位置依次为 6、7、0、1，下一次入队写到 2。

## 原始来源

- [栈与队列接口](https://opendatastructures.org/ods-python/1_2_Interfaces.html)
- [数组队列与模运算](https://opendatastructures.org/ods-python/2_3_ArrayQueue_Array_Based_.html)
- [单链表实现栈与队列](https://opendatastructures.org/ods-python/3_1_SLList_Singly_Linked_Li.html)
