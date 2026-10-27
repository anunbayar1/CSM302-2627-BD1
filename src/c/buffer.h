/* buffer.h — OS Concepts (10th ed.), Chapter 7, Programming Project 4 */
#ifndef BUFFER_H
#define BUFFER_H

typedef int buffer_item;

#ifndef BUFFER_SIZE
#define BUFFER_SIZE 5          /* can be overridden: make BUFFER_SIZE=10 */
#endif

int  buffer_init(void);         /* initialise mutex, empty and full          */
void buffer_destroy(void);
int  insert_item(buffer_item item);   /* 0 on success, -1 on error / shutdown */
int  remove_item(buffer_item *item);  /* 0 on success, -1 on error / shutdown */

#endif
