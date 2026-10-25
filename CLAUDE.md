# Software description
An AI Agent that implements tasks 1-by-1 from boards (Trello, etc.):
- Picks tasks from "To Do" column, identifies relevant repo(s) from `repos.md`, implements the task, moves it to "To Review" with a comment describing what was done
- Per task: creates a branch, commits regularly, merges `main` into the branch, and if all works merges the branch back to `main`
- If stuck or has questions: writes a comment with all relevant questions and moves the task to "Waiting for answers". If no user reply within 48h, auto-answers using best assumptions from similar products online, the current product, and common sense
- currently trello implemnted and connected

# Safety
AI coding agent including  must not expose or print or put to print in log sensetive or secure keys values, such as .env, however its allowed to parse .env which is in format VAR=key, and read only VAR and key's length or substring of key length and use the relevant keys in the code at secured way

# Workflow overrides
  - For superpowers Skip brainstorming/planning skills; implement directly unless I ask otherwise.
  - For superpowers when in executing or executing-plans mode - execute until all done, don't stop and ask me every step what to do next, decide by yourself and continue to execute until the whole plan is done 

# Code quality requirements (primary)
All created code must:
1. Work, be secured, have no ambiguity, no unreachable/unused code
2. Have an intuitive, beautiful GUI
3. Potentially increase ROI; optimized for user's conversion to the next step
4. Second priority: relatively fast, scalable

# General development guidelines
1. Act as BDD (Behavior Driven Development); keep code concise and correct
2. Include logs for easy debug, unit tests, end-to-end tests, and traceability (balanced). Logs must contain errors
3. Keep methods and functions (including `main`) up to 20 lines
4. Keep files up to 300 lines
5. Any DB schema change must be safe and preserve existing data
6. Code and prompts must be safe and secure
7. If you install something or change setup that users running an older version on another server may also need, add it to `scripts/[optional_subfolder]/`
8. You must not expose key or secured tokens, if needed, so you can split relevant files contains VARIABLE=[SECRET] and read only VARIABLE, you must not read the SECRET in any scenario!!!

# Adding a new feature (BDD process)
1. Explore all code relevant to the feature
2. Prepare a plan that includes a BDD test plan and a feature implementation plan
3. Write the BDD test plan (unit tests + end-to-end tests)
4. Implement the plan
5. Write unit tests per the BDD plan for each feature/sub-feature; run and fix until it matches the user's initial plan
6. Write end-to-end tests per the BDD plan for each e2e feature/sub-feature; run and fix until it matches the user's initial plan. The plan must test with connected board and at keast test with trello which is Currently implemenetd and connected


# Frontend guidelines
1. UX/UI must be beautiful, frictionless, and responsive

# Backend guidelines
1. First priority: easy to implement and concise
2. Second priority: high performance

# md files instructions
1. On changes, update relevant md files. Keep `README.md` and `CLAUDE.md` aligned to the code, concise, containing only necessary data
2. Additional md files go under `docs/` or `docs/[subfolder]/`

# Cleanup
1. Before finishing a session, or after full implementation and successful testing of large features, shut down unnecessary processes and dockers via bash scripts and verify they are shut down — without losing any DB data
