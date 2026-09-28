# 学生提交注意事项

做题及提交注意事项

在提交时要注意多测试几次，避免测试时出现异常情况导致结果不正确。

本系统现在不支持中文输入输出，请勿在程序中输入输出中文。

**1、提交工程文件：加法的例子**

题目描述：

将输入的2个整数的和输出。

注意：

任意多余输出视为错误。

例如

输入

5 10

输出

**15 提交：**

- ①提交没做说明可提交整个工程文件

- ②提交未通过编译的工程0分。

- ③提交工程，主函数如下：

```cpp
#include<stdio.h>
void main() {
       int a,b;
       scanf("%d",&a);
       scanf("%d",&b);
       printf("%d",a+b);
}
```

可得到满分。

- ④提交工程，主函数有多余输出如下：

```cpp
#include<stdio.h>
void main() {
       int a,b;
       printf("请输入a：");
       scanf("%d",&a);
       printf("请输入b：");
       scanf("%d",&b);
       printf("%d+%d=%d",a,b,a+b);
}
```

算错，不得分。

- ⑤提交工程，主函数需要额外的输入才能返回，如下：

```cpp
#include<stdio.h>
#include<stdlib.h>
void main() {
       int a,b;
       printf("请输入a：");
       scanf("%d",&a);
       printf("请输入b：");
       scanf("%d",&b);
       printf("%d+%d=%d",a,b,a+b);
       system(
"pause "); //需要额外输入才能返回
}
```

算错，不得分。

**2、只提交源文件：另一个加法的例子**

题目描述：

实现add方法：

```cpp
void add(int *
result);
```

在add方法中，从输入得到2个整数，将和保存在result中。

注意：

- ①仅提交含有add方法实现的源文件（不含主函数），add.cpp。

- ②遇到异常情况，输出"ERROR"（大写）；否则不要随意输出。

提交：

- ①仅提交含有add方法实现的源文件，add.cpp。

提示，做题时，可将add方法放在add.cpp中，主函数放在main.cpp中，但是提交时仅提交add.cpp。

- ②提交的源代码有错误，无法通过编译。得0分。

例如如下，缺少include语句

```cpp
void add(int *
result) {
       if(
result==0 ) {
              printf("ERROR");
              return;
       }
       int a,b;
       scanf("%d",&a);
       scanf("%d",&b);
       *
result = a+b;
}
```

- ③提交的add.cpp如下，

```cpp
#include<stdio.h>
void add(int *
result) {
       if(
result==0 ) {
              printf("ERROR");
              return;
       }
       int a,b;
       scanf("%d",&a);
       scanf("%d",&b);
       *
result = a+b;
}
```

可得到满分。

- ④提交的add.cpp如下，

包括了自己的头文件"myhead.h"，

如果提交的压缩包中含有myhead.h，则可通过编译。

如果提交的压缩包中未含有myhead.h，则无法通过编译，0分。

```cpp
#include"myhead.h"
#include<stdio.h>
void add(int *
result) {
       if(
result==0 ) {
              printf("ERROR");
              return;
       }
       int a,b;
       scanf("%d",&a);
       scanf("%d",&b);
       *
result = a+b;
}
```

- ⑤提交的add.cpp如下，

另外含有main方法，0分。

```cpp
#include"myhead.h"
#include<stdio.h>
void main() {
}
void add(int *
result) {
       if(
result==0 ) {
              printf("ERROR");
              return;
       }
       int a,b;
       scanf("%d",&a);
       scanf("%d",&b);
       *
result = a+b;
}
```
