# Demo — Issue #11 (AWS runtime ADR)

**Branch:** `feature/issue-11-aws-runtime-adr`  
**Issue:** [intotheopen/intotheopen-backend#11](https://github.com/intotheopen/intotheopen-backend/issues/11)

| Criterion | Deliverable |
| --------- | ----------- |
| Chosen architecture | **EC2 + Docker Compose** (MVP); ECS deferred |
| Deploy / rollback documented | ADR-001 sections (detail in #20) |
| Security assumptions listed | Trust boundaries + constraints in ADR |

```bash
pytest tests/test_aws_runtime_adr.py -q
```
