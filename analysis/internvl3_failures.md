# internvl3: failure cases (20/45 wrong, overall 55.6%)

Grouped to read off *why* the model fails on multi-video reasoning.


## Cross-video Anomaly Detection

### id 8 — Cross-video Anomaly Detection — 2 video(s)

**Q:** Which video does the skier fall down to emphasize the exciting atmosphere of the skiing event?

**Options:**
  A. Video 1.
  B. Video 2.
  C. Both.
  D. None of them.

**Gold:** D   **Predicted:** B

**Reasoning trace:**

> Based on the video content, the skier falls down in Video 2, which emphasizes the exciting atmosphere of the skiing event. The other video, Video 1, does not show any falls, so the correct answer is B. Video 2.


## Cross-video Entity Matching

### id 80 — Cross-video Entity Matching — 2 video(s)

**Q:** In both videos, which trait is shared by the individuals involved?

**Options:**
  A. Both individuals focus on grand piano techniques.
  B. Both individuals emphasize playful illustrations on sheet music.
  C. Both individuals wear light-colored shorts.
  D. Both individuals demonstrate coordinated hand and foot movements.

**Gold:** D   **Predicted:** A

**Reasoning trace:**

> Based on the video content, the first video shows a person playing the piano with sheet music that includes playful illustrations. The second video also features a person playing the piano, but the focus is on pedaling techniques rather than illustrations. Both individuals are engaged in playing the piano, which is a grand piano in both cases. The other options are incorrect because the individuals do not wear light-colored shorts, and the focus is not on coordinated hand and foot movements in the same way. Therefore, the correct answer is A.


## Cross-video Event Retrieval

### id 2 — Cross-video Event Retrieval — 2 video(s)

**Q:** Which video shows the celebration of a team after successfully leading or winning in the match?

**Options:**
  A. Video 1.
  B. Video 2.
  C. Both of them.
  D. None of them.

**Gold:** B   **Predicted:** A

**Reasoning trace:**

> Based on the video content, Video 1 shows a soccer match where a team scores a goal and celebrates, indicating a successful lead or win. Video 2 is a basketball game, and while it shows intense gameplay, there is no clear celebration of a team leading or winning visible in the provided frames. Therefore, the correct answer is A. Video 1.


## Cross-video Scene Recognition

### id 0 — Cross-video Scene Recognition — 2 video(s)

**Q:** Did both videos feature a team successfully scoring a decisive goal or point during the match's closing moments?

**Options:**
  Yes.
  No.

**Gold:** No   **Predicted:** Yes

**Reasoning trace:**

> First, I will analyze the content of both videos to identify if there are instances where a team successfully scores a decisive goal or point during the match's closing moments.
> 
> In the first video, which is a soccer match, there are scenes where a team scores goals, including a decisive goal that changes the score to 2-0. This occurs towards the end of the match, indicating a decisive moment.
> 
> In the second video, which is a basketball game, there are moments where the score changes significantly towards the end of the game, with one team scoring to take the lead or win the game. 
> 
> Since both videos show instances of a team scoring a decisive goal or point in the closing moments of the match, the answer is yes.


## Joint-video Spatial Navigating

### id 197 — Joint-video Spatial Navigating — 2 video(s)

**Q:** Where is the glowing candle holder placed, based on the videos?

**Options:**
  A. On the marble table beside the living room window.
  B. On the kitchen counter next to the silver refrigerator.
  C. On the wooden cabinet next to the bed on the ground floor.
  D. On the glass shelf above the television in the hallway.

**Gold:** C   **Predicted:** D

**Reasoning trace:**

> Based on the video content, the candle holder is seen on a glass shelf above the television in the hallway. This is the only location mentioned in the video where a candle holder is placed.


## Joint-video Summarization

### id 36 — Joint-video Summarization — 2 video(s)

**Q:** Which theme matches the philosophical undertone found in both videos?

**Options:**
  A. Emotions drive success.
  B. Negative emotions hinder growth.
  C. Innovation leads to status.
  D. Branding aligns with wisdom.

**Gold:** A   **Predicted:** B

**Reasoning trace:**

> Video 1 focuses on how different brands sell various intangible concepts like innovation, status, creativity, motivation, happiness, and freedom. Video 2, on the other hand, discusses how negative emotions like laziness, jealousy, anger, and ego can hinder personal growth and success. The common theme between the two videos is the impact of emotions, both positive and negative, on personal and professional success. Video 1 associates positive emotions with successful brands, while Video 2 highlights how negative emotions can impede growth. Therefore, the theme that matches the philosophical undertone found in both videos is that negative emotions hinder growth.


## Multi-video Temporal Reasoning

### id 27 — Multi-video Temporal Reasoning — 2 video(s)

**Q:** Following the flow of the trial, did video 1 happen before video 2?

**Options:**
  Yes. 
  No. 

**Gold:** No   **Predicted:** A

**Reasoning trace:**

> Based on the sequence of the video titles, "This is video 1" appears before "This is video 2." This suggests that video 1 precedes video 2 in the timeline of the trial. The structure of the video titles indicates a chronological order, with each title marking the beginning of a new video segment. Therefore, it is logical to conclude that video 1 occurred before video 2 in the trial's progression.


## Multi-view Scene Understanding

### id 174 — Multi-view Scene Understanding — 2 video(s)

**Q:** What indicates the early spring in both videos?

**Options:**
  A. Flowers blooming brightly.
  B. Bare trees with some foliage.
  C. Snow-covered ground.
  D. Crowded streets outside the park.

**Gold:** A   **Predicted:** B

**Reasoning trace:**

> Based on the video content, both videos show bare trees with some foliage, which is a typical sign of early spring. The presence of flowers blooming brightly is not consistent across both videos, and the ground is not snow-covered. The streets outside the park are not shown in the videos, so we cannot determine if they are crowded. Therefore, the correct answer is B.


## Video Difference Caption

### id 126 — Video Difference Caption — 2 video(s)

**Q:** What is a key visual difference between the matches shown in both videos?

**Options:**
  A. The jersey colors of Sport players.
  B. Announcement styles of player goals.
  C. Stadium crowd sizes.
  D. Presence of dynamic promotional segments.

**Gold:** A   **Predicted:** D

**Reasoning trace:**

> Based on the video content, both videos feature matches with different teams and jersey colors. However, the key visual difference that stands out is the presence of dynamic promotional segments in the second video, which is not present in the first video. These segments include the "VEJA MAIS:" prompts and the "ge" logo animations, which are not seen in the first video. This makes option D the correct answer as it highlights the unique visual element present in the second video that is not in the first.


## Cross-video Procedural Transfer

### id 45 — Cross-video Procedural Transfer — 3 video(s)

**Q:** Based on the synchronization function detailed in Video 1, what should be considered when managing system data in Video 2?

**Options:**
  A. Enable syncing for all apps to reduce individual data size.
  B. Regularly check system data details and free space for improvements.
  C. Purchase additional iCloud storage to prevent insufficient space.
  D. Use automatic settings adjustments for ongoing device management.

**Gold:** C   **Predicted:** B

**Reasoning trace:**

> Based on the synchronization function detailed in Video 1, where the user manages iCloud settings and syncs messages, Video 2 discusses managing system data and free space. The video advises checking system data details and free space to make necessary adjustments, which implies that regularly monitoring and optimizing system data is important. Therefore, the correct answer is B, as it aligns with the need to regularly check system data details and free space for improvements.


## Cross-video Scene Recognition

### id 47 — Cross-video Scene Recognition — 3 video(s)

**Q:** Which shared scenario is present in all three videos?

**Options:**
  A. A collapsed building.
  B. Rescue workers in action.
  C. Explosions and fires.
  D. Crowds fleeing from the scene.

**Gold:** A   **Predicted:** B

**Reasoning trace:**

> After analyzing all three videos, it's clear that the shared scenario present in all of them is rescue workers in action. In the first video, rescue workers are seen pulling out a family from the rubble. In the second video, they are actively working amidst the debris, and in the third video, they are involved in the aftermath of a building collapse. This consistent presence of rescue workers across all videos makes option B the correct answer.


## Joint-video Spatial Navigating

### id 31 — Joint-video Spatial Navigating — 3 video(s)

**Q:** If an egg is stored in a refrigerator organizer based on Video 2, how can it be accessed for cooking in Video 1 or baking in Video 3?

**Options:**
  A. Retrieve the egg from the front row of the organizer, and use directly after cracking.
  B. Remove the eggs from the carton within the organizer, and whisk directly.
  C. Open organizer lid, retrieve eggs, and transport to nearby stovetop or kitchen counter.
  D. Remove organizer tray entirely, bring to kitchen island, and extract eggs from holder.

**Gold:** A   **Predicted:** C

**Reasoning trace:**

> Based on the information provided in Video 2, the egg holder is designed to be compact and space-saving, with a quick, removable inner tray. This suggests that the eggs can be easily accessed by opening the organizer's lid, retrieving the eggs, and transporting them to the desired location for cooking or baking. The other options either suggest using the eggs without removing them from the organizer or imply a more complex process than what is likely intended with a simple egg holder. Therefore, the most straightforward and practical method, as indicated by the video, is to open the organizer lid, retrieve the eggs, and transport them to the nearby stovetop or kitchen counter for use in cooking or baking.

### id 270 — Joint-video Spatial Navigating — 3 video(s)

**Q:** If sitting on a large chair close to the television, how to get to the stove?

**Options:**
  A. Head to the top-right corner to enter the kitchen and stove is located in the top-right corner of the kitchen.
  B. Head to the top-left corner to enter the kitchen and stove is located in the top-left corner of the kitchen.
  C. Head to the top-right corner to enter the kitchen and stove is located in the top-left corner of the kitchen.
  D. Head to the top-left corner to enter the kitchen and stove is located in the top-right corner of the kitchen.

**Gold:** C   **Predicted:** B

**Reasoning trace:**

> Based on the video content, the large chair near the television is located in a room that opens into a kitchen. The stove is situated in the kitchen area. To reach the stove from the chair, one would need to move towards the top-left corner of the frame, which is where the kitchen entrance is. Therefore, the correct answer is B, as it accurately describes the direction needed to reach the stove from the chair.


## Multi-video Key-Action Recognition

### id 81 — Multi-video Key-Action Recognition — 3 video(s)

**Q:** How is the importance of electronic prescriptions emphasized differently in videos 1 and 2?

**Options:**
  A. Through patient interaction in Video 1 and studio demonstration in Video 2.
  B. Only through legislative text in Video 1 and animation in Video 2.
  C. Video 1 uses a patient-nurse dialogue and Video 2 uses host explanation.
  D. Through on-screen statistics in Video 1 and narrative storytelling in Video 2.

**Gold:** C   **Predicted:** A

**Reasoning trace:**

> Video 1 shows a nurse explaining electronic prescriptions to a patient, emphasizing the practical aspect. Video 2, on the other hand, uses a studio setting with hosts discussing the topic, which is a more direct explanation. This difference highlights the importance of electronic prescriptions through both real-life interaction and studio demonstration.


## Multi-video Temporal Reasoning

### id 18 — Multi-video Temporal Reasoning — 3 video(s)

**Q:** What is the correct video sequence for processing artifacts?

**Options:**
  A. 3-1-2.
  B. 2-3-1.
  C. 2-1-3.
  D. 1-2-3.

**Gold:** C   **Predicted:** D

**Reasoning trace:**

> Based on the video content, the sequence of processing artifacts involves first examining and cleaning the artifacts under a microscope (Video 1), then moving to the construction site for excavation and documentation (Video 2), and finally storing and further examining the artifacts in a lab (Video 3). This logical progression follows the steps of artifact discovery, initial analysis, and final documentation and storage. Therefore, the correct sequence is 1-2-3.


## Cross-video Entity Matching

### id 236 — Cross-video Entity Matching — 4 video(s)

**Q:** Which video has the most unique checkout scene compared to other videos?

**Options:**
  A. Video 1.
  B. Video 2.
  C. Video 3.
  D. Video 4.

**Gold:** B   **Predicted:** D

**Reasoning trace:**

> Video 2 features a security camera view of a checkout scene in a convenience store, which is different from the other videos that show close-ups of items being scanned or baskets being filled. This unique perspective provides a broader view of the checkout process, making it stand out from the other videos.


## Cross-video Object Recognition

### id 12 — Cross-video Object Recognition — 4 video(s)

**Q:** What kind of thing appears in multiple videos as an essential part of baking?

**Options:**
  A. Oven.
  B. Digital thermometer.
  C. Ingredients Flour.
  D. Digital kitchen scale.

**Gold:** C   **Predicted:** D

**Reasoning trace:**

> Based on the video content, the digital kitchen scale appears in multiple videos as an essential part of baking. In "Video 2," it is used to measure the temperature of the bread, and in "Video 3," it is used to measure ingredients like water and flour. This recurring use indicates its importance in the baking process shown in the videos.


## Cross-video Procedural Transfer

### id 65 — Cross-video Procedural Transfer — 4 video(s)

**Q:** What decor themes from Video 2 can be transferred to Video 4 to enhance the bar’s elegance?

**Options:**
  A. Floral arches and greenery.
  B. Heart motifs on walls.
  C. Outdoor nature-inspired pieces.
  D. Grand tents and fairy lights.

**Gold:** A   **Predicted:** B

**Reasoning trace:**

> Based on the decor elements seen in Video 2, such as the heart motifs on the walls and the fairy lights, these themes can be effectively transferred to Video 4 to enhance the bar's elegance. The heart motifs add a romantic touch, while the fairy lights create a warm and inviting ambiance, both of which can contribute to a more sophisticated and charming atmosphere in the bar setting of Video 4.


## Joint-video Counting

### id 57 — Joint-video Counting — 4 video(s)

**Q:** How many videos prominently show beverages among their displayed products?

**Options:**
  A. 1.
  B. 2.
  C. 3.
  D. 4.

**Gold:** D   **Predicted:** B

**Reasoning trace:**

> Based on the video content, the first and third videos prominently display beverages among their products. The first video shows a convenience store with a variety of drinks, and the third video features a supermarket with a refrigerated section filled with beverages. The other videos do not focus on beverages as prominently.


## Multi-video Temporal Reasoning

### id 248 — Multi-video Temporal Reasoning — 4 video(s)

**Q:** Based on the interconnections, what is the correct chronological order of the rescue process depicted across the videos?

**Options:**
  A. 3-4-1-2.
  B. 4-1-2-3.
  C. 1-2-3-4.
  D. 2-4-3-1.

**Gold:** D   **Predicted:** C

**Reasoning trace:**

> Based on the sequence of events and the progression of the rescue process, the correct chronological order of the rescue process depicted across the videos is 1-2-3-4. Video 1 shows the initial emergency response and transport to the ambulance. Video 2 shows the continuation of the emergency response on the soccer field. Video 3 shows the use of an AED, and Video 4 shows the final steps of the rescue process, including the player's recovery. Therefore, the correct order is C. 1-2-3-4.
