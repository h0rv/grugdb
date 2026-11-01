# 7. Build a B+ tree

When you insert a key into the middle of chapter 6's sorted index, the list
moves every entry after it. Postgres, SQLite, and MySQL use a **B+ tree** for
their indexes instead. A B+ tree splits one long sorted list into many short
lists and puts a small index on top of them:

```text
                 [ 30 | 60 ]                internal node: separator keys
              /       |       \
   [10 20 25] -> [30 41 52] -> [60 70 88]   leaves: keys + row IDs, linked
```

Each node holds at most a few entries, so an insert moves only a few entries.
All leaves are at the same depth, so every lookup follows a path of the same
length from the root. The leaves are linked from left to right. A range scan
finds its first key once and then follows the links, without going back to the
root.

In this picture, a separator equals the smallest key in its right child. The
separator 30 means "keys of 30 or more are in the child to my right". To find a
key, start at the root and take the child to the right of the last separator
that is less than or equal to the key. To find 41, you pass 30 but not 60, so
you go to the middle leaf.

## A split, step by step

Say each leaf holds at most 3 keys, and you insert 22 into the tree above. The
search leads to the first leaf, which now holds 4 keys:

```text
[10 20 22 25]                          too many keys
```

Split it into two leaves of 2 keys each. The smallest key of the new right leaf,
22, becomes a separator in the parent:

```text
                 [ 22 | 30 | 60 ]
              /     |      |     \
   [10 20] -> [22 25] -> [30 41 52] -> [60 70 88]
```

The parent now has 3 separators and 4 children. If the parent also had too many
separators, it would split in the same way and push one separator up to its own
parent. When the root splits, you create a new root above it, and the tree gets
one level taller. A new root is the only way the tree grows taller, so every
leaf stays at the same depth.

## Borrowing and merging

A delete works in the other direction. With at most 3 keys per leaf, a common
minimum is 2 keys. The root is the one node allowed to hold fewer.

Delete 22 from the tree above, and the leaf `[22 25]` drops to `[25]`, which is
below the minimum. First try to borrow. The left neighbor `[10 20]` has only 2
keys, so it cannot give one away. The right neighbor `[30 41 52]` has 3, so move
30 into the short leaf. The leaves become `[25 30]` and `[41 52]`, and the
parent's separator for the right leaf changes from 30 to 41, its new smallest
key.

If neither neighbor has a key to spare, merge the short leaf with a neighbor and
remove the separator between them from the parent. That can leave the parent
short, so the same repair continues one level up. When the root is left with a
single child, that child becomes the new root, and the tree gets one level
shorter.

## Your turn

Create `src/grugdb/bplus_tree.py` with `InternalNode`, `Leaf`, and `BPlusTree`.
It implements the same `add`, `remove`, `lookup`, and `range` methods as chapter
6's `SortedIndex`, so it can replace that index without changes to the rest of
the engine.

Decide these before you write code:

- Entry identity. Store `(key, row_id)` so that duplicate keys stay distinct.
- The separator rule. This chapter uses "a separator equals the smallest entry
  in its right child". If you pick a different rule, your search must follow it.
- Occupancy. Use a small maximum, e.g., 3 keys per leaf, so that tests cause
  many splits. A minimum of half the maximum, rounded up, works. The root may
  have fewer than the minimum.

Then build the tree in this order, and test each step before the next:

1. `lookup` on a tree you build by hand.
1. `add` into a leaf with room.
1. Leaf splits.
1. Internal splits, including the root.
1. `range` across linked leaves.
1. `remove` with borrowing, merging, and the root shrinking.

## Check the structure as well as the answers

A broken B+ tree can return correct answers for a while and then fail on a later
insert. To catch this early, write `BPlusTree.check()`. It walks the whole tree
and asserts each rule:

- Keys are sorted within each node.
- Every child's keys fall inside its separators.
- All leaves are at the same depth.
- Every node except the root has at least the minimum number of entries.
- The leaf chain visits every entry once, in order.

Then compare the tree with a plain sorted list, which is easy to get right.
Apply a long random sequence of inserts and deletes from a fixed seed to both.
After every operation, call `check()` and compare the `lookup` and `range`
results.

Done when:

- `check()` passes after every step of thousands of random operations.
- `lookup` and `range` always match the sorted list.
- Ascending inserts, descending inserts, and duplicate keys all work.
- Deleting every entry shrinks the tree back to an empty root.
- Removing a missing entry always does what you documented.

Write these tests in `tests/test_bplus_tree.py`.

<!-- local-only:start -->

When working locally, run the B+ tree tests from the repository root:

```sh
python -m unittest tests.test_bplus_tree
```

<!-- local-only:end -->

## Compare the speed

The B+ tree may be slower than the sorted list. With a few thousand keys,
`bisect` and the list shift run in C, and Python objects are slow in comparison.
The B+ tree does better at large sizes, and most of all on disk. On disk, each
node is one page, and a lookup that reads fewer pages is faster. Add a benchmark
to `bench/run.py` that compares `BPlusTree` with `SortedIndex` on the same
workload. Check that the results match, and find the size at which the tree
becomes faster on your machine. Run these measurements with local CPython.

Real B+ trees use much bigger nodes. Each node is one disk page, usually 4 to 16
KB, and an internal node holds hundreds of children. With that many children per
node, a tree over millions of keys is only 2 to 4 levels deep, so a lookup reads
2 to 4 pages. Postgres uses a variant called a Lehman and Yao B-link tree, which
adds a link from each node to its right neighbor so that readers and writers can
work at the same time. Postgres also does not merge pages after a delete. It
only reclaims pages that become completely empty.

Storing these nodes in disk pages would be a large project. It needs a byte
encoding, a page cache, and page writes that survive a crash. In this course,
the tree stays in memory, and grugdb rebuilds it from the rows when it loads a
database.

## Go deeper

- [Anatomy of an SQL index](https://use-the-index-luke.com/sql/anatomy) has
  pictures of leaf nodes and the tree above them.
- Andy Pavlo's [index lecture](https://www.youtube.com/watch?v=scUtG_6M_lU)
  covers splits and deletes.
- Alex Petrov's
  [storage talk](https://www.infoq.com/presentations/storage-algorithms/)
  explains separator keys and how splits move up the tree.

Next: [query planning](08-planning.md).
