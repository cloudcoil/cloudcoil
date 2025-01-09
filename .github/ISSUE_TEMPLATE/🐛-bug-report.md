---
name: "\U0001F41B Bug report"
about: Help us fix something!
title: ''
labels: 'type:bug'
assignees: ''

---

<h2>Pre-bug-report checklist</h2>

**1. This bug can be reproduced using kubectl**
- [ ] Yes [👉 Please report a bug to the Kubernetes GitHub 👈](https://github.com/kubernetes/kubernetes/issues/new/choose)
- [ ] No

_If yes, it is more likely to be an Kubernetes bug unrelated to Cloudcoil. Please double check before submitting an issue to Cloudcoil._

**2. I have searched for [existing issues](https://github.com/cloudcoil/cloudcoil/issues)**
- [ ] Yes

**3. This bug occurs in Cloudcoil when...**
- [ ] Performing CRUD operations on Resources
- [ ] Using the Cloudcoil code-generator
- [ ] Parsing/Exporting from files or YAML
- [ ] other: 

<h2>Bug report</h2>

**Describe the bug**
_A clear and concise description of what the bug is:_

_Error log if applicable_:
```
error: something broke!
```

**To Reproduce**
Full Cloudcoil code to reproduce the bug:
```py
from cloudcoil.models import kubernetes as k8s

...
```

**Expected behavior**
_A clear and concise description of what you expected to happen:_


**Environment**
- Cloudcoil Version: 0.X.X
- Python Version: 3.X.X
- Kubernetes Version: 1.X.X

**Additional context**
Add any other context about the problem here.
