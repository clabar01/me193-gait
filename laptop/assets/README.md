# 3D avatar assets (not in git)

`laptop/dashboard.html` loads these Mixamo files for its 3D avatar. They are
gitignored: Mixamo's terms allow using them in a project but not
redistributing the files themselves, and this repo is public. Without them the
dashboard shows the stick figure.

To set them up, download from [mixamo.com](https://www.mixamo.com) (free Adobe
account) with the same character for every file, **FBX Binary**, **In Place**
ticked where offered, and save them here under exactly these names:

| File | Mixamo animation | Used for |
| --- | --- | --- |
| `Standing Idle.fbx` | Standing Idle, **With Skin** | the character mesh + standing |
| `Walking.fbx` | Walking | walking |
| `Running.fbx` | Running | running |
| `Flying Bicycle Kick.fbx` | Flying Bicycle Kick | biking (seated, hands on bars) |
| `Bicycle Crunch.fbx` | Bicycle Crunch | air-biking (on your back) |

Only `Standing Idle.fbx` needs the skin; the others can be "Without Skin"
(much smaller). The file names are set in the 3D AVATAR section of
`dashboard.html` (`CHARACTER`, `CLIPS`). Each clip should loop once per stride
or pedal turn; if a new one loops twice, set its `CYCLES` entry to 2.
