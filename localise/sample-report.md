# English localisation: 200-template sample (Claude API)

Model `claude-opus-5-5`, batches of 40, line-numbered plain text, system prompt (instructions + glossary) marked `cache_control: ephemeral`. Prices: $4/MTok input, $20/MTok output, $0.20/MTok cache read, $5/MTok cache write (1.25x input).

Sample: 60 names (glossary pass, translated first) + 140 other templates; 2,620 template chars. Full set: 11,083 templates, 157,921 chars (scale factor 60.3x).

## Usage and cost per effort level

| effort | calls | failed calls | input | output | cache write | cache read | API time s | sample cost $ | full projection $ | full via Batches API $ |
|---|---|---|---|---|---|---|---|---|---|---|
| low | 7 | 1 | 5,176 | 4,938 | 2,522 | 8,051 | 47 | 0.1337 | 8.06 | 4.03 |
| medium | 6 | 0 | 4,189 | 6,703 | 1,856 | 6,926 | 61 | 0.1615 | 9.73 | 4.87 |

## Glossary overhead in the full run

Instructions alone: 686 tokens; with the 60-name sample glossary: 1,863 tokens (19.6 tokens per entry).
The full set has 2,885 name templates, so a complete glossary is about 56,594 tokens. Sent cached with each of the 205 non-name batches that is about 11.6 MTok of cache reads, $2.32 (plus one cache write of $0.28 per 5-minute window). The char-scaled projection above does not include this; add it. Sending only the glossary entries that occur in each batch would make it negligible.

## 40 representative rows

| kind | Chinese | low | medium |
|---|---|---|---|
| UI string | %s-印记 | %s - Mark | %s - Mark |
| UI string | (通过特殊途径获得稀有道具,使用后解锁) | (Rare item from special sources. Use to unlock.) | (Rare item obtained through special sources. Use to unlock.) |
| UI string | 你不在的时候，你的%s经过了哥的调教，增长了%s点经验值，不用谢,哥是活雷锋~~ | While you were away, I gave your %s some training and it gained %s EXP. No need to thank me, I'm just that generous~~ | While you were away, I trained your %s and it gained %s EXP. No need to thank me, I'm just a good Samaritan~~ |
| UI string | 光环 | Aura | Aura |
| UI string | 刚刚 | Just now | Just now |
| UI string | 在魔王地宫中获得的代币，实力的象征，可在魔王地宫商店中购买物品. | Tokens earned in the Archfiend's Lair, a symbol of strength. Spend them in the Archfiend's Lair Shop. | Tokens earned in the Demon Lord's Crypt. A symbol of strength, they can be spent in the Demon Lord's Crypt Shop. |
| UI string | 女神试炼 -- 宝箱个数是# | Angel Trial: # Chests | Angel Trial - Chests: # |
| UI string | 屏蔽 | Block | Block |
| UI string | 您的金币数量不足 | Not enough Gold | Not enough Gold |
| UI string | 查看商品 | View Items | View Item |
| UI string | 符文能量已满 | Rune Energy is full | Rune Energy is full |
| UI string | 钻石不足 | Not enough Diamonds | Not enough Diamonds |
| hero | 帝国戍卫 | Imperial Guard | Imperial Sentinel |
| hero | 极光之刃 | Aurora Blade | Aurora Blade |
| hero | 美杜莎 | Medusa | Medusa |
| hero | 驱魔人 | Exorcist | Exorcist |
| item | 【圣诞小鹿】头像 | [Christmas Reindeer] Avatar | [Christmas Reindeer] Avatar |
| item | 极光寒冰圣披风碎片 | Aurora Frost Holy Cloak Shard | Aurora Frost Holy Cloak Shard |
| item | 神秘灵魂石(冰蓝之泪) | Mystic Soulstone (Frost Tear) | Mystic Soul Stone (Azure Tear) |
| item/event/mail text | 完成普通关卡：森林夜幕# | Clear Normal Stage: Forest Nightfall # | Clear Normal Stage: Forest Nightfall # |
| item/event/mail text | 打开后可获得紫耀石之杖*#、紫耀石之盔*#、金耀石至宝*# | Open to receive Amethyst Staff*#, Amethyst Helm*#, Topaz Treasure*# | Open to receive: Violet Shine Staff*#, Violet Shine Helm*#, Golden Shine Treasure*# |
| item/event/mail text | 打开后可获得：光辉*#、星辰*#、天道*#、魔宗*#、霸王*# | Open to receive: Radiance*#, Stars*#, Heaven's Way*#, Demon Sect*#, Overlord*# | Open to receive: Radiance*#, Starlight*#, Heaven's Path*#, Demon Sect*#, Overlord*# |
| item/event/mail text | 散发着偏深色的光芒 | Gives off a deep, dark glow | Gives off a deep, dark glow |
| item/event/mail text | 获得将军爵位 | Earn the General Rank | Earn the rank of General |
| item/event/mail text | 蕴含神秘的力量，是光明神使进阶#星的必备材料 | Holds a mysterious power. Required to advance Light Envoy to #-Star | Holds a mysterious power. Required to Advance Light Envoy to # Stars. |
| item/event/mail text | 觉醒石(守护者) | Awakening Stone (Guardian) | Awakening Stone (Guardian) |
| server message | 女神光环点非空 | Angel Aura points are not empty | Angel Aura points are not empty |
| server message | 雇佣次数不足 | Not enough hire attempts | Not enough hire attempts |
| skill | 烈焰之速 | Blazing Speed | Blazing Speed |
| skill | 连珠火球 | Chain Fireballs | Fireball Barrage |
| skill/buff description | 唤法之灵符文#的描述 | Spellcaller Spirit Rune # description | Spellcaller Spirit Rune # description |
| skill/buff description | 回复#点怒气 | Restores # Rage | Restores # Rage |
| skill/buff description | 提升#点暴击与#点暴击伤害 | Increases Crit by # and Crit DMG by # | Increases Crit by # and Crit Damage by # |
| skill/buff description | 时空女皇将敌方攻击最高的单位禁锢在另一个时空中，对其造成#.#%伤害，使其沉默并降低#%魔防，持续#回合 | The Time Empress imprisons the enemy with the highest ATK in another dimension, dealing #.#% damage, Silencing them and reducing M.DEF by #% for # turns | Chrono Empress imprisons the enemy with the highest Attack in another dimension, dealing #.#% damage, Silencing them and lowering their Magic Defense by #% for # turns |
| skill/buff description | 潘多拉技能二#描述 | Pandora Skill 2 # description | Pandora Skill 2 # description |
| stage | 训练假人 | Training Dummy | Training Dummy |
| stage/story text | “天空一声巨响 劳资闪亮登场！”随着一声轰鸣，一个全身闪电环绕的怪物出现在了众人面前 | "A thunderclap in the sky, and here I come in style!" With a roar, a monster wreathed in lightning appears before everyone | "A thunderclap splits the sky, and here I come in all my glory!" With a deafening roar, a monster wreathed in lightning appears before everyone |
| stage/story text | 她体内所散发出的极光之力，正是多年来引发雪之国上空异象的真正原因 | The aurora power radiating from within her is the true cause of the strange phenomena over the Snow Kingdom all these years | The aurora power radiating from within her is the true cause of the strange phenomena in the skies over the Snow Kingdom all these years |
| stage/story text | 虽然我们只是领盒饭的，但是我们也有尊严！ | We may just be extras, but we have our dignity too! | We may just be extras, but we have our dignity too! |
| stage/story text | 走呀走呀，走到了一间茅屋前，要不要敲三下呢？ | On and on you walk until you reach a thatched hut. Knock three times? | On and on you walk, until you reach a thatched hut. Knock three times? |

## Batches that failed validation

Calls rejected and retried: low/text: 1.

None after the one retry.
