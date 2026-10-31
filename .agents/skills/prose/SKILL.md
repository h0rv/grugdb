---
name: prose
description: Write or edit grugdb lessons, the introduction, README, and course documentation. Use for explanations, examples, exercise instructions, and revisions to course writing.
---

# Prose

Write the way an experienced engineer explains something to a colleague. State
what is true, why it is true, and what it costs. The reader is a Python
programmer who uses databases and has never built one.

Plain does not mean short. Explain every step the reader needs. Cut everything
else.

## Rules

- Use simple, everyday words. Repeat a word instead of swapping in a synonym.
- Write complete sentences. One sentence states one thing.
- Do not use dashes. Use a colon only to introduce a list or a code block.
- Define a technical term once, in plain words, the first time it appears.
- Describe the actual thing. Do not use metaphors or comparisons.
- Make a person or the program the actor. Do not give an idea or a number an
  action, e.g., write "you pay for this at commit time", not "the cost comes
  due".
- Use real numbers from runs on this repository. Never invent one.
- Mention each edge case once, where it first matters.
- Separate code that runs today from code the reader builds. Label code that
  only works after an exercise.
- Teach the idea fully, but do not give an exercise's solution as pseudocode.

## Patterns to avoid

These patterns make text read as machine-written. Do not use them.

- A list of three for rhythm, e.g., "no SQL, no ORM, and no conversion". Use a
  bullet list when there are separate items.
- "Here is a ..." followed by a colon, as a setup for a reveal.
- Saying what something is not, then what it is, e.g., "It is not decoration. It
  is the schema." Say what it is.
- A short sentence that repeats the previous point as a punchline, e.g., "That's
  the payoff."
- Sentence fragments for drama, e.g., "Three. Not a million."
- A question that the next sentence answers, e.g., "Why not? Because ...".
- Claims about stakes or about the reader, e.g., "this matters", "the price is",
  "surprises most people".
- Emphasis words that add no information, e.g., "just", "simply", "exactly",
  "real", "really".
- Bold text at the start of bullets or paragraphs.
- A recap line at the end of a section that restates the section.

## Chapter layout

Start with the idea, stated plainly. Then explain it with the smallest example.
Then say which file to edit and give a short "Done when" list of behaviors and
the test command. Put outside links under "Go deeper" at the end. Leave out any
part that does not help the chapter.

## Recurring ideas

- Queries are plain Python. The database does not convert values, so the rows
  you get back are the objects you stored. Conditions are expressions built from
  field references, so the planner can read them.
- The type annotations are the schema. Knowing each field's type is what makes
  indexes, planning, and compact storage possible.
- Each design choice should come with a number you can reproduce with
  `poe bench` or a short script.
