---
title: How to use this path
minutes: 12
objectives:
  - Know how the folders, labs and guided walkthrough work
  - Pick a study plan that fits the time you have
  - Understand what is verified and what is illustrative
---
This is a self-paced path. Each topic folder opens with one interactive page. The left side lists every section, the top bar moves you between sections and topics, and **Start** walks you through every concept automatically.

@concept The shape of every concept
@plain
Every concept in this path is taught the same way, so you always know where to look. First a short explanation in everyday words. Then the problem the idea exists to solve. Then what it does. Then a diagram that you can replay.
@problem
Most technical material explains *how* before it explains *why*. Beginners then memorise commands without knowing when to use them, and cannot make good decisions later.
@does
- Gives a three-part summary at the top of each concept: **In plain words**, **The problem it solves**, **What it does**.
- Follows with a diagram that lights up one step at a time.
- Ends with commands, a decision table and quick self-check questions where they help.
@diagram flow
caption: The four parts of every concept, in order
numbered: true
nodes:
  - "In plain words|the idea in simple terms|info"
  - "The problem|why it exists|bad"
  - "What it does|how it behaves|ok"
  - "Diagram + code|see it, then run it|env"
@check
Why does every concept start with the problem? || Because knowing the problem lets you judge when a tool is the right choice, which is the core skill of an architect.
@end

@concept Choosing a study plan
@plain
The path has fifteen topic folders. You do not have to read them all in one go. Pick the plan that matches your time and goal.
@problem
A long curriculum feels overwhelming and people quit after the first few topics. A clear plan with milestones keeps progress visible.
@does
- Offers three plans of different depth.
- Shows how each plan maps to a job role.
- Marks which sections are required and which are optional deep dives.
@diagram cmp
caption: Three study plans
cards:
  - {h: "Fast track (about 10 hours)", kind: ok, items: ["Read every section's first concept", "Do the labs marked LAB", "Build the Shop sample app once"]}
  - {h: "Steady (6 to 8 weeks)", kind: app, items: ["One topic per week", "All labs, all checks", "Replay each diagram until you can redraw it"]}
  - {h: "Architect track (3 to 4 months)", kind: env, items: ["Everything in Steady", "Write a decision record per topic", "Rebuild the Shop on a second cloud"]}
@choose Which plan fits you
Fast track | you need a working overview this week, or are moving from another field | you must pass an exam or take an architect interview soon
Steady | you work full time and want depth that sticks | you only need one tool, such as Terraform
Architect track | you are targeting a design role and want to justify choices | you have no hands-on time at all
@end

@concept How to read the labs
@plain
A **LAB** box contains commands you can run. The explanations do not depend on running them, so you can learn the ideas by reading alone.
@problem
Cloud labs cost money and break easily. Requiring every learner to run every command would exclude people without accounts or budget.
@does
- Marks every command block that changes real systems.
- Keeps local-only commands separate from commands that create cloud resources.
- Always shows the clean-up command next to the create command.
@diagram flow
caption: Lab cost ladder, from free to billable
nodes:
  - "Read only|no setup, no cost|ok"
  - "Local|your laptop, free|info"
  - "Free tier|small cloud usage|warn"
  - "Billable|EKS, NAT, load balancers|bad"
@end

:::warn
Anything that creates cloud infrastructure is clearly labelled. Always run the matching destroy step, and set a billing alert before you start. A forgotten NAT gateway or load balancer costs money every hour.
:::

@concept What is verified and what is illustrative
@plain
Version numbers change quickly. Pages take them from one file, `tools/versions.yaml`, so they can be updated in one place, and the build fails if a page names a version that does not exist there.
@problem
Outdated version numbers are the most common reason a tutorial stops working. A curriculum that hides where its numbers come from cannot be trusted or maintained.
@does
- Marks each version as **verified** (read from the upstream release index on the build date) or **example** (illustrative).
- Validates every YAML, JSON, Python, Bash and Terraform snippet for syntax during the build.
- States clearly when something was not run against a real cloud account.
@diagram flow
caption: How a version number reaches a page
nodes:
  - "versions.yaml|single source|cp"
  - "Page uses a placeholder|the version key|plain"
  - "Build checks the key|fails if unknown|warn"
  - "HTML shows the value|always consistent|ok"
@end

:::note
This curriculum was assembled without running a real cluster or cloud account. Syntax is machine-checked; behaviour described comes from documented design. Treat commands as a starting point and confirm in a sandbox account first.
:::
