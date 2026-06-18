# CrossView (UT Austin Multi-Camera) — the 60 questions we evaluated

Subset: `analysis/crossview_subset.json` — 60 MEVA questions (20 Temporal + 20 Event-Ordering + 20 Spatial), capped to <=4 cameras.

Columns per question: source · task_type · orig cameras (true synchronized count) · videos the model saw (<=4) · gold answer.


### Q0 — CrossView-MEVA-Event-Ordering
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Put the following moments in the order they happened: I. A vehicle makes a right turn II. A black-haired person in a black top, navy pants, and navy shoes—wearing a hat and carrying a bag—walks into view through a doorway III. A navy-haired person in a navy top and black pants—wearing a hat and scarf and carrying a bag—sets an object down IV. A blue-haired person in a navy top and black pants with black shoes—wearing a scarf and carrying a bag—picks an object up Which sequence is correct?**

- A. III -> I -> II -> IV
- B. IV -> I -> II -> III
- C. IV -> II -> I -> III ✅
- D. II -> IV -> I -> III

**Gold answer: C**

### Q1 — CrossView-MEVA-Event-Ordering
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Put these four moments in the order they happened: I. A black-haired person in a dark green top, indigo pants, and indigo shoes, wearing a scarf, walks into view through a doorway II. A vehicle begins moving III. A black-haired person in an olive top, black pants, and navy shoes, wearing a hat, is texting on a phone IV. A vehicle reverses Which sequence is correct?**

- A. II -> IV -> I -> III
- B. III -> IV -> I -> II
- C. III -> I -> IV -> II ✅
- D. I -> III -> IV -> II

**Gold answer: C**

### Q2 — CrossView-MEVA-Event-Ordering
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Put the following observed moments in the order they happened: I. A person in a navy top and navy pants hands an object to someone II. A black-haired person in a navy top, black pants, and black shoes, carrying a bag, hands an object to someone III. A black-haired person wearing a hat, dressed in a black top and black pants with navy shoes, carrying a bag, talks on the phone IV. A vehicle picks up an object Which sequence is correct?**

- A. II -> IV -> I -> III
- B. III -> IV -> I -> II
- C. III -> I -> IV -> II ✅
- D. I -> III -> IV -> II

**Gold answer: C**

### Q3 — CrossView-MEVA-Event-Ordering
*orig_cameras=5 · videos_seen=4 · cap_answer_safe=True*

**Put these captured moments in the order they happened: I. A vehicle begins to move II. A person in a plum top and purple pants gets into a vehicle III. A person is talking on the phone IV. A vehicle makes a right turn Which sequence is correct?**

- A. III -> I -> II -> IV
- B. IV -> I -> II -> III
- C. IV -> II -> I -> III ✅
- D. II -> IV -> I -> III

**Gold answer: C**

### Q4 — CrossView-MEVA-Event-Ordering
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Put these moments in the order they happened: I. A person with indigo hair in a patterned dark plum top gets into a vehicle II. A person in a blue top and white dress with black shoes shuts a vehicle door III. Someone makes a right turn IV. A white-haired person in a white top and white dress gets out of a vehicle Which sequence is correct?**

- A. II -> IV -> I -> III
- B. III -> IV -> I -> II
- C. III -> I -> IV -> II ✅
- D. I -> III -> IV -> II

**Gold answer: C**

### Q5 — CrossView-MEVA-Event-Ordering
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Put these moments in the order they happened: I. A person with blue hair in a dark indigo top, black pants, and blue shoes talks to another person II. A person with indigo hair, wearing a blue top, light patterned blue pants, navy shoes, and a hat, exits through a doorway and disappears from view III. A person begins to move IV. A vehicle makes a left turn Which sequence is correct?**

- A. III -> I -> II -> IV
- B. IV -> I -> II -> III
- C. IV -> II -> I -> III ✅
- D. II -> IV -> I -> III

**Gold answer: C**

### Q6 — CrossView-MEVA-Event-Ordering
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Four different actions were captured in the footage. Arrange these events in the order they happened: I. A vehicle begins moving II. A person sits down III. A vehicle makes a right turn IV. A person turns left Which sequence is correct?**

- A. IV -> II -> III -> I
- B. III -> I -> II -> IV
- C. I -> II -> III -> IV
- D. I -> III -> II -> IV ✅

**Gold answer: D**

### Q7 — CrossView-MEVA-Event-Ordering
*orig_cameras=5 · videos_seen=4 · cap_answer_safe=True*

**Put these vehicle-related moments in the order they happened: I. A person in a white top and indigo pants gets into a vehicle II. A person in a navy top and blue pants opens a vehicle door III. A person in a blue top and navy pants shuts a vehicle door IV. A person in a white top and indigo pants gets out of a vehicle Which sequence is correct?**

- A. I -> III -> II -> IV
- B. IV -> III -> II -> I
- C. IV -> II -> III -> I ✅
- D. II -> IV -> III -> I

**Gold answer: C**

### Q8 — CrossView-MEVA-Event-Ordering
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Put these moments into the order they happened: I. A person in a patterned white top and a white dress, carrying a bag, steps out of a vehicle II. Someone shuts the vehicle door III. A person gets into a vehicle IV. Someone opens a vehicle door Which sequence is correct?**

- A. II -> IV -> I -> III
- B. III -> IV -> I -> II
- C. III -> I -> IV -> II ✅
- D. I -> III -> IV -> II

**Gold answer: C**

### Q9 — CrossView-MEVA-Event-Ordering
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Put the following moments in the order they happened, based on what was seen across the different views: I. A vehicle pulls away and begins moving II. A vehicle comes to a complete stop III. A black-haired person in a black top and black pants, carrying a bag, picks up an object IV. A tall, black-haired person wearing a hat, dressed in a black top, black pants, and black shoes, carrying a bag, hands an object to someone Which sequence is correct?**

- A. II -> IV -> I -> III
- B. III -> IV -> I -> II
- C. III -> I -> IV -> II ✅
- D. I -> III -> IV -> II

**Gold answer: C**

### Q10 — CrossView-MEVA-Event-Ordering
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Put these moments in the order they happened, based on what’s seen in the footage: I. A person in a white top and white dress opens a vehicle door II. Someone closes a vehicle door III. A black-haired person wearing a black top, black pants, black shoes, and a hat—carrying a bag—stands up IV. A person in a white top and white dress opens a vehicle door again Which sequence is correct?**

- A. II -> IV -> I -> III
- B. III -> IV -> I -> II
- C. III -> I -> IV -> II ✅
- D. I -> III -> IV -> II

**Gold answer: C**

### Q11 — CrossView-MEVA-Event-Ordering
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Put these captured moments in the order they happened: I. A black-haired person wearing a black top and black pants with khaki shoes, a hat, and a bag picks up an object II. A person in a white top and white dress opens a vehicle door III. A person in a white top and white dress opens a vehicle door IV. Someone closes a vehicle door Which sequence is correct?**

- A. IV -> II -> III -> I
- B. III -> I -> II -> IV
- C. I -> II -> III -> IV
- D. I -> III -> II -> IV ✅

**Gold answer: D**

### Q14 — CrossView-MEVA-Event-Ordering
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Three moments were captured in the footage. Put these events in the order they happened: I. A black-haired person in a black top and black pants with gold shoes, carrying a bag, exits the view through a doorway II. A teal-haired person in a dark rust top and dark black pants with black shoes, wearing a hat and sunglasses and carrying a bag, opens a facility door III. A black-haired person in a black top and black pants with black shoes, wearing a hat and sunglasses and carrying a bag, talks to another person What is the correct chronological sequence?**

- A. I -> III -> II
- B. III -> II -> I
- C. II -> III -> I ✅
- D. II -> I -> III

**Gold answer: C**

### Q15 — CrossView-MEVA-Event-Ordering
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Three doorway moments were captured on the surveillance feeds. Put these events in the order they happened: I. A black-haired person wearing a navy top and a dark rust dress, with a scarf, exits the frame through a doorway. II. A black-haired person in a black top and black pants, wearing gold shoes and carrying a bag, exits the frame through a doorway. III. A teal-haired person wearing a dark rust top and dark black pants, with black shoes, a bag, a hat, and sunglasses, enters the frame through a doorway. What sequence is correct?**

- A. I -> III -> II
- B. II -> I -> III
- C. III -> I -> II ✅
- D. III -> II -> I

**Gold answer: C**

### Q16 — CrossView-MEVA-Event-Ordering
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Put the following observed moments in the order they happened: I. A black-haired person in a teal top, dark blue pants, and gold shoes—wearing a hat and scarf and carrying a bag—stands up. II. An indigo-haired person in a plum top, black pants, and black shoes—wearing a hat and carrying a bag—exits through a doorway and disappears from view. III. A black-haired person in a navy top and navy pants with black shoes—wearing a scarf and carrying a bag—opens a facility door. IV. A black-haired person in a black top and black pants with indigo shoes leaves through a doorway and goes out of view. What sequence is correct?**

- A. II -> IV -> I -> III
- B. III -> IV -> I -> II
- C. III -> I -> IV -> II ✅
- D. I -> III -> IV -> II

**Gold answer: C**

### Q22 — CrossView-MEVA-Event-Ordering
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Put these moments in the order they happened, based on what was seen across the video feeds: I. A black-haired person in a black top and black skirt with blue shoes is texting on a phone. II. A black-haired person wearing a black top and black pants, with a hat, comes into view through a doorway. III. An indigo-haired person in a dark navy top and dark black pants with navy shoes, carrying a bag and wearing a hat, scarf, and sunglasses, closes a facility door. What sequence is correct?**

- A. I -> III -> II
- B. III -> II -> I
- C. II -> III -> I ✅
- D. II -> I -> III

**Gold answer: C**

### Q26 — CrossView-MEVA-Event-Ordering
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Put these observed moments in the order they happened: I. A person with indigo hair, wearing a navy top, dark olive pants, olive shoes, and a hat, exits the view through a doorway II. A person with indigo hair, wearing a dark blue top, dark indigo pants, navy shoes, and a hat, opens a facility door III. A person with black hair, wearing a black top and a black dress, enters the view through a doorway Which sequence is correct?**

- A. III -> I -> II
- B. I -> II -> III
- C. II -> III -> I
- D. III -> II -> I ✅

**Gold answer: D**

### Q34 — CrossView-MEVA-Event-Ordering
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Put these doorway-related moments in the order they happened: I. A black-haired person in a black top and black dress with a scarf exits the view through a doorway. II. A black-haired person in a black top and black pants with navy shoes enters the view through a doorway. III. A black-haired person in a dark teal top carrying a bag leaves the view through a doorway. IV. A black-haired person wearing a hat, dressed in a black top and black pants with navy shoes, carrying a bag, opens a facility door. What sequence is correct?**

- A. III -> I -> II -> IV
- B. IV -> I -> II -> III
- C. IV -> II -> I -> III ✅
- D. II -> IV -> I -> III

**Gold answer: C**

### Q48 — CrossView-MEVA-Event-Ordering
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Multiple doorway-related actions were captured across the different views. Put these moments in the order they happened: I. A person with indigo hair, wearing an indigo top and navy pants with navy shoes, plus a hat and sunglasses, walks into view through a doorway II. A person with indigo hair, wearing a black top and blue pants with navy shoes, carrying a bag, walks into view through a doorway III. A person with indigo hair, wearing a dark indigo top and black pants with black shoes, carrying a bag, opens a facility door IV. A person with black hair, wearing a black top and a black dress, with a hat and scarf, carrying a bag, exits view through a doorway What is the correct sequence?**

- A. II -> IV -> I -> III
- B. III -> IV -> I -> II
- C. III -> I -> IV -> II ✅
- D. I -> III -> IV -> II

**Gold answer: C**

### Q53 — CrossView-MEVA-Event-Ordering
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Put these captured moments in the order they happened: I. A black-haired person in a black top and black dress with charcoal shoes walks into view through a doorway II. A black-haired person in a black top and black pants with black shoes, carrying a bag, walks into view through a doorway III. A black-haired person in a navy top and black pants with black shoes, carrying a bag, opens a facility door Which sequence is correct?**

- A. III -> I -> II
- B. II -> III -> I
- C. I -> II -> III
- D. II -> I -> III ✅

**Gold answer: D**

### Q297 — CrossView-MEVA-Spatial
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close does the person in black pants with indigo shoes get to the person wearing a dark indigo top with dark gray pants and dark gray shoes?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q298 — CrossView-MEVA-Spatial
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the black-haired person in a navy top and black pants (wearing a hat and carrying a bag) and the black-haired person dressed all in black (also wearing a hat and carrying a bag) get to each other?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q299 — CrossView-MEVA-Spatial
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the black-haired person dressed all in black with a hat and a bag get to the black-haired person in a blue top, black pants, and black shoes who is also carrying a bag?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q300 — CrossView-MEVA-Spatial
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**In the footage, what is the closest distance between the black-haired person in a navy top, black pants, and black shoes—wearing a hat and carrying a bag—and the black-haired person in an indigo top, black pants, and black shoes—also wearing a hat and carrying a bag?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q301 — CrossView-MEVA-Spatial
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the indigo-haired person in a light blue top with black pants and black shoes get to the blue-haired person wearing a dark indigo top with black pants and blue shoes?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q302 — CrossView-MEVA-Spatial
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the teal-haired person in a blue top and dark blue dress with indigo shoes get to the white-haired person wearing an indigo top, black pants, and indigo shoes?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q303 — CrossView-MEVA-Spatial
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the teal-haired person in a blue top and dark blue dress with indigo shoes and the blue-haired person in a dark indigo top, black pants, and blue shoes get to one another?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q304 — CrossView-MEVA-Spatial
*orig_cameras=5 · videos_seen=4 · cap_answer_safe=True*

**In the scene, how close do the two people wearing a blue top and white pants—one getting into a vehicle and the other speaking with someone—come to each other?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q307 — CrossView-MEVA-Spatial
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the two black-haired individuals—each dressed in a black top, black pants, black shoes, and a hat—get to one another?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q308 — CrossView-MEVA-Spatial
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the maroon-haired person in a rust-colored top with dark rust pants and rust shoes get to the black-haired person wearing a black top and navy pants?**

- A. They approach and stay near each other (within a few meters)
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters) ✅
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: C**

### Q309 — CrossView-MEVA-Spatial
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the black-haired person dressed in a black top and black pants with gold shoes and the black-haired person in a black top with navy pants get to one another?**

- A. They approach and stay near each other (within a few meters)
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters) ✅
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: C**

### Q310 — CrossView-MEVA-Spatial
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the black-haired person in a blue top and white skirt and the black-haired person in a black top with navy pants and navy shoes get to one another?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q311 — CrossView-MEVA-Spatial
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the two navy-haired people in black tops—one in dark blue pants with navy shoes and the other in navy pants with black shoes—get to each other?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q312 — CrossView-MEVA-Spatial
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**In the footage, how close do the black-haired person in a dark indigo top and navy pants get to the navy-haired person wearing a black top, navy pants, and black shoes?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q471 — CrossView-MEVA-Spatial
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**In the footage, how close do the two people—one dressed in a navy top with navy pants and the other in a navy top with black pants—get to each other?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q472 — CrossView-MEVA-Spatial
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**In the footage, how close do the two people—one in a black top with navy pants and the other in a black top with black pants—get to each other at their nearest point?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q473 — CrossView-MEVA-Spatial
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**In the footage, how close do the two people dressed in a navy top and navy pants—one opening a facility door and the other exiting through a doorway—get to each other?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q474 — CrossView-MEVA-Spatial
*orig_cameras=3 · videos_seen=3 · cap_answer_safe=True*

**In the footage, how close do the tall person in a navy top and navy pants get to the person with navy hair who’s also wearing a navy top and navy pants, along with plum shoes and a hat?**

- A. They approach and stay near each other (within a few meters) ✅
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: A**

### Q475 — CrossView-MEVA-Spatial
*orig_cameras=3 · videos_seen=3 · cap_answer_safe=True*

**In the footage, how close does the person in a blue top with navy pants get to the person wearing a navy top and navy pants?**

- A. They approach and stay near each other (within a few meters)
- B. They stay at a moderate distance (5-15 meters apart) ✅
- C. They remain far apart (more than 15 meters)
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: B**

### Q476 — CrossView-MEVA-Spatial
*orig_cameras=3 · videos_seen=3 · cap_answer_safe=True*

**In the footage, how close does the person in a teal top with navy pants get to the person in an olive top with navy pants?**

- A. They approach and stay near each other (within a few meters)
- B. They stay at a moderate distance (5-15 meters apart)
- C. They remain far apart (more than 15 meters) ✅
- D. They walk past each other, swapping positions (cross paths)

**Gold answer: C**

### Q728 — CrossView-MEVA-Temporal
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Which happened first: the person with indigo hair wearing an olive top, dark indigo pants, indigo shoes, and a hat leaving through a structure, or the black-haired person in a patterned green top, navy pants, indigo shoes, and a hat talking on the phone?**

- A. The person with indigo hair, wearing an olive top and dark indigo pants, indigo shoes, with a hat, exiting a scene through a structure occurred first ✅
- B. The person with black hair, wearing a patterned green top and navy pants, indigo shoes, with a hat, talking on a phone occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q729 — CrossView-MEVA-Temporal
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Which happened first: the black-haired person in a dark green top with indigo pants and indigo shoes, wearing a scarf, walking in through a structure, or someone opening a facility door?**

- A. The person with black hair, wearing a dark green top and indigo pants, indigo shoes, with a scarf, entering a scene through a structure occurred first
- B. The person opening a facility door occurred first ✅
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: B**

### Q730 — CrossView-MEVA-Temporal
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Between these two moments, which happened first: the person in a blue top and blue pants closing a trunk, or the black-haired person dressed in black with black shoes, wearing a hat and carrying a bag, sitting down?**

- A. The person, wearing a blue top and blue pants, closing a trunk occurred first ✅
- B. The person with black hair, wearing a black top and black pants, black shoes, with a hat, carrying a bag, sitting down occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q731 — CrossView-MEVA-Temporal
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Which happened first: the black-haired person in a black top with navy pants and navy shoes, wearing sunglasses and carrying a bag, putting an object down, or the person in a blue top and blue pants closing a vehicle door?**

- A. The person with black hair, wearing a black top and navy pants, navy shoes, with a sunglasses, carrying a bag, putting down object occurred first
- B. The person, wearing a blue top and blue pants, closing a vehicle door occurred first ✅
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: B**

### Q732 — CrossView-MEVA-Temporal
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Which happened first: the person in a blue top and white dress with black shoes opening a vehicle door, or the person in a black top with charcoal shoes talking on a phone?**

- A. The person, wearing a blue top and white dress, black shoes, opening a vehicle door occurred first ✅
- B. The person, wearing a black top, charcoal shoes, talking on a phone occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q733 — CrossView-MEVA-Temporal
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Between these two moments, which happened first: a white-haired person in a white top and white dress opening a trunk, or a person in a white top and white dress with black shoes getting out of a vehicle?**

- A. The person with white hair, wearing a white top and white dress, opening a trunk occurred first
- B. The person, wearing a white top and white dress, black shoes, exiting a vehicle occurred first ✅
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: B**

### Q734 — CrossView-MEVA-Temporal
*orig_cameras=5 · videos_seen=4 · cap_answer_safe=True*

**Between these two moments, which happened first: a person in a white top and indigo pants getting into a vehicle, or the vehicle starting?**

- A. The person, wearing a white top and indigo pants, entering a vehicle occurred first ✅
- B. The vehicle starting occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q735 — CrossView-MEVA-Temporal
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Which happened earlier: the navy-haired person in a navy top and navy pants opening a vehicle door, or the teal-haired person in a navy top, blue skirt, and navy shoes interacting with someone?**

- A. The person with navy hair, wearing a navy top and navy pants, opening a vehicle door occurred first ✅
- B. The person with teal hair, wearing a navy top and blue skirt, navy shoes, interacting with a person occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q736 — CrossView-MEVA-Temporal
*orig_cameras=12 · videos_seen=4 · cap_answer_safe=True*

**Between these two moments, which happened first: the black-haired person in a dark black top, black pants, black shoes, and a hat walking in through a structure, or that same person opening a facility door?**

- A. The person with black hair, wearing a dark black top and black pants, black shoes, with hat, entering a scene through a structure occurred first
- B. The person with black hair, wearing a dark black top and black pants, black shoes, with hat, opening a facility door occurred first ✅
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: B**

### Q743 — CrossView-MEVA-Temporal
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Which happened first: the teal-haired person in a dark rust top and dark black pants, wearing black shoes and carrying a bag while also wearing a hat and sunglasses, walking in through a structure—or the black-haired person dressed in a black top and black pants with black shoes, wearing a hat and sunglasses and carrying a bag, talking to someone?**

- A. The person with teal hair, wearing a dark rust top and dark black pants, black shoes, with bag, hat, sunglasses, entering a scene through a structure occurred first ✅
- B. The person with black hair, wearing a black top and black pants, black shoes, with a hat and sunglasses, carrying a bag, talking to a person occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q744 — CrossView-MEVA-Temporal
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Between these two moments, which happened first: the short person with teal hair in a dark rust top, dark black pants, and black shoes—carrying a bag and wearing a hat and sunglasses—walking in through a structure, or the person with teal hair dressed the same way opening a facility door?**

- A. The short person with teal hair, wearing a dark rust top and dark black pants, black shoes, with bag, hat, sunglasses, entering a scene through a structure occurred first
- B. The person with teal hair, wearing a dark rust top and dark black pants, black shoes, with bag, hat, sunglasses, opening a facility door occurred first ✅
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: B**

### Q745 — CrossView-MEVA-Temporal
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Which happened earlier: the navy-haired person in a dark olive top with navy pants and navy shoes embracing someone, or the navy-haired person in a navy top with dark black pants and indigo shoes carrying a heavy object?**

- A. The person with navy hair, wearing a dark olive top and navy pants, navy shoes, embracing a person occurred first ✅
- B. The person with navy hair, wearing a navy top and dark black pants, indigo shoes, carrying a heavy object occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q746 — CrossView-MEVA-Temporal
*orig_cameras=7 · videos_seen=4 · cap_answer_safe=True*

**Between these two moments, which happened first: a black-haired person dressed in a black top and black pants with blue shoes, carrying a bag while talking on the phone, or a person in a light blue top and blue dress wearing a hat, carrying a bag, opening a vehicle door?**

- A. The person with black hair, wearing a black top and black pants, blue shoes, carrying a bag, talking on a phone occurred first
- B. The person, wearing a light blue top and blue dress, with a hat, carrying a bag, opening a vehicle door occurred first ✅
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: B**

### Q747 — CrossView-MEVA-Temporal
*orig_cameras=5 · videos_seen=4 · cap_answer_safe=True*

**Which happened first: a vehicle backing up, or a person with teal hair in a patterned gray top, navy pants, and navy shoes talking on the phone?**

- A. The vehicle reversing occurred first ✅
- B. The person with teal hair, wearing a patterned gray top and navy pants, navy shoes, talking on a phone occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q748 — CrossView-MEVA-Temporal
*orig_cameras=5 · videos_seen=4 · cap_answer_safe=True*

**Between these two moments, which happened first: a person in a black top with navy pants and navy shoes opening a facility door, or a person closing a vehicle door?**

- A. The person, wearing a black top and navy pants, navy shoes, opening a facility door occurred first
- B. The person closing a vehicle door occurred first ✅
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: B**

### Q751 — CrossView-MEVA-Temporal
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Which happened first: the black-haired person in a blue top, dark indigo pants, and navy shoes opening a facility door, or that same person exiting through a structure?**

- A. The person with black hair, wearing a blue top and dark indigo pants, navy shoes, opening a facility door occurred first ✅
- B. The person with black hair, wearing a blue top and dark indigo pants, navy shoes, exiting a scene through a structure occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q752 — CrossView-MEVA-Temporal
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Between these two moments, which happened first: a black-haired person in a black top and black skirt with blue shoes texting on a phone, or an indigo-haired person in a dark navy top and dark black pants with navy shoes—wearing a bag, hat, scarf, and sunglasses—closing a facility door?**

- A. The person with black hair, wearing a black top and black skirt, blue shoes, texting on a phone occurred first
- B. The person with indigo hair, wearing a dark navy top and dark black pants, navy shoes, with bag, hat, scarf, sunglasses, closing a facility door occurred first ✅
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: B**

### Q759 — CrossView-MEVA-Temporal
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Which happened earlier: the indigo-haired person in a dark blue top and dark indigo pants with navy shoes and a hat opening a facility door, or the indigo-haired person in a dark indigo top and black skirt with black shoes, a hat and scarf, carrying a bag, exiting through a structure?**

- A. The person with indigo hair, wearing a dark blue top and dark indigo pants, navy shoes, with a hat, opening a facility door occurred first ✅
- B. The person with indigo hair, wearing a dark indigo top and black skirt, black shoes, with a hat and scarf, carrying a bag, exiting a scene through a structure occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q766 — CrossView-MEVA-Temporal
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Which happened first: the indigo-haired person in a dark black top and dark black pants with black shoes, carrying a bag and wearing a hat and scarf, opening a facility door, or that same person entering through a structure?**

- A. The person with indigo hair, wearing a dark black top and dark black pants, black shoes, with bag, hat, scarf, opening a facility door occurred first ✅
- B. The person with indigo hair, wearing a dark black top and dark black pants, black shoes, with bag, hat, scarf, entering a scene through a structure occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**

### Q779 — CrossView-MEVA-Temporal
*orig_cameras=2 · videos_seen=2 · cap_answer_safe=True*

**Between these two moments, which happened first: the teal-haired person in a dark black top, light black pants, and black shoes, carrying a bag, opening a facility door, or that same person walking in through a structure?**

- A. The person with teal hair, wearing a dark black top and light black pants, black shoes, with bag, opening a facility door occurred first ✅
- B. The person with teal hair, wearing a dark black top and light black pants, black shoes, with bag, entering a scene through a structure occurred first
- C. They occurred simultaneously
- D. Cannot be determined

**Gold answer: A**