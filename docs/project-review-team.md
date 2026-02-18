# Project Review Team

This project includes a dedicated review squad for full-system assessment:

- `project_review_architecture`
- `project_review_reliability`
- `project_review_security`
- `project_review_product`
- `project_review_delivery`
- `project_review_board` (final synthesis)

## Suggested Workflow

1. Ingest the repository docs/source for search context.
2. Dispatch specialist reviewers in parallel.
3. Send all specialist outputs to `project_review_board` for a final grade and prioritized roadmap.

## Example Chief Prompt

Use this with the chief orchestrator:

```text
Run a full project review.
1) Ingest the repository at /Users/jasricha/Documents/GitHub/chief_of_staff.
2) Dispatch these agents in parallel with the same task: evaluate the whole project, provide a grade, key risks, and top improvements:
   - project_review_architecture
   - project_review_reliability
   - project_review_security
   - project_review_product
   - project_review_delivery
3) Pass all five outputs to project_review_board.
4) Return one final report with:
   - weighted final grade
   - P0/P1 items
   - 0-2 week, 2-6 week, and 6+ week roadmap.
```
