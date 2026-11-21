# Team setup evidence

Initial owned session `/tmp/motionmate-preview-session-66cizc_y` failed during
atomic synthetic Team seeding: long surname exceeded the existing 30-character
field. No application validation was changed. Corrected the synthetic surname.
The failed fixture transaction rolled back; the owned BEFORE cluster was stopped
through verified tooling. That session and its original logs remain preserved;
no reset/reseed/cleanup or ordinary-database action occurred. A fresh independent
session uses the same authorized ports and frozen BEFORE snapshot.
