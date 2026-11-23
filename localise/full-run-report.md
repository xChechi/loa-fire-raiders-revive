# English localisation: full run (effort medium)

Model `claude-opus-5-5`, normal Messages API, batches of up to 40 lines / 4000 chars. Order: hero and angel names, the other names with the hero/angel glossary, then all other text with the full glossary. Medium-effort rows from the sample were reused, not re-paid.

## Counts

| pass | templates | translated | missing after retry |
|---|---|---|---|
| names-1 | 113 | 113 | 0 |
| names-2 | 2,772 | 2,772 | 0 |
| text | 8,236 | 8,236 | 0 |
| total | 11,121 | 11,121 | 0 |

## Tokens and cost

| run | calls | rejected calls | input | output | cache write | cache read | API time min | USD |
|---|---|---|---|---|---|---|---|---|
| drift (all) | 1 | 0 | 1,077 | 1,748 | 0 | 61,003 | 0 | 0.0515 |
| full (all) | 277 | 2 | 237,857 | 368,648 | 186,059 | 12,474,204 | 52 | 11.7495 |
| sample (medium) | 6 | 0 | 4,189 | 6,703 | 1,856 | 6,926 | 1 | 0.1615 |

All API spend on this project so far (both sample efforts + full run): $12.0962.

## Templates missing after retry

None.

Failure reasons per batch (last attempt):

- text: line 28: placeholders differ (missing {}, extra {'#': 1}); line 29: placeholders differ (missing {}, extra {'#': 1}); line 30: placeholders differ (missing {}, extra {'#': 1}); line 33: placeholders differ (missing {}, extra {'#': 1}); line 34: placeholders differ (missing {}, extra {'#': 1}); line 35: placeholders differ (missing {}, extra {'#': 1}); line 36: placeholders differ (missing {}, extr

## Glossary consistency (top 30)

72 glossary names have at least one non-name translation that contains the Chinese name but not its glossary English (case-insensitive substring check; names under 2 chars or with `#` skipped). Some are inflections or plurals, not real mismatches.

| Chinese name | glossary English | mismatches / uses | example text | its English |
|---|---|---|---|---|
| 觉醒 | Awakening | 146 / 180 | %s未达到本次觉醒条件 | %s does not meet the requirements for this Awaken |
| 精灵 | Elf | 62 / 83 | “绿精灵套装”之一 | Part of the "Green Sprite Set" |
| 圣灵 | Holy Spirit | 18 / 28 | 圣灵守护者觉醒技能加免伤 | Holy Guardian Awaken Skill DMG Reduction Up |
| 血族 | Vampires | 17 / 32 | 血族王子#技能免疫物理 | Vampire Prince Skill # Physical Immunity |
| 利刃 | Keen Edge | 12 / 12 | 魔之利刃 | Demon Blade |
| 驱魔 | Exorcism | 11 / 13 | 可合成驱魔披风。 | Used to craft Exorcist Cloak. |
| 光之继承 | Legacy of Light | 10 / 11 | 护佑功能规则说明:\n#.护佑功能允许联盟队长将已培养英雄和女神放至指定的护佑勋章中，来为对应类型的英雄增加属性。比如战之斗魂勋章要求狂暴之爪、小女巫、光之继承者和恶魔猎人，只要玩家将这#位英雄上阵，并可以为所有战士职业英雄增加攻击相关的属性，而不是为这#位英雄增加属性\n#.英雄的类型目前分为职业和性别两种\n#.勋章会随着联盟等级分批开启。\n#.每个勋章初期只会开放#个女神位+#个英雄位，其余的#个英雄位需要玩家在公会秘藏玩法中积攒栏位解锁符来开启。\n#.英雄和女神的培养程度会影响各自的评分，评分会影响最终所能够增加的属性（评分并不完全通过总战力计算，每个能力点能提供的评分各不相同）。\n      影响英雄评分的元素:\n            等级、星级、装备、技能、符文\n      影响女神评分的元素:\n            等级、星级、技能、光环\n | Blessing Rules:\n#. Blessing lets the Alliance Captain place trained Heroes and Angels in specific Blessing Medals to boost stats for Heroes of the matching type. For example, the War Spirit Medal requires Frenzy Claw, Little Witch, Heir of Light and Demon Hunter. Once the player deploys these # Heroes, all Warrior Heroes gain attack-related stats, rather than only these # Heroes.\n#. Hero types are currently divided by class and gender.\n#. Medals unlock in batches as Alliance Level rises.\n#. Each Medal initially opens only # Angel slot + # Hero slots; the remaining # Hero slots are unlocked with Slot Unlock Charms collected in the Guild Vault.\n#. How well Heroes and Angels are trained affects their Rating, and Rating determines the final stat bonus (Rating is not based solely on total Power; each attribute point contributes a different amount).\n      Factors affecting Hero Rating:\n            Level, Stars, Gear, Skills, Runes\n      Factors affecting Angel Rating:\n            Level, Stars, Skills, Aura\n |
| 毁灭 | Destruction | 10 / 13 | 炎龙烈阳具有强大的毁灭之力，天神为了保护使用者用万龙之鳞打造的圣戒 | Dragonsun wields immense destructive power. To protect its wielder, the gods forged this holy ring from the scales of a myriad dragons. |
| 复仇 | Revenge | 9 / 11 | #级的复仇女神光环# | Lv.# Nemesis Aura # |
| 战争机器 | War Machine | 9 / 9 | 战争机器人医疗形态buff# | War Mech Medic Form Buff # |
| 烈焰之怒 | Wrath of Flames | 7 / 10 | 收集#个碎片合成烈焰之怒戒指 | Collect # shards to craft Ring of Blazing Fury |
| 星辰 | Stars | 6 / 23 | 星辰规则说明:\n\n#.每个英雄品质达到紫色+#开启星辰培养，品质达到紫色+#、橙色时开启第二、第三、第四、第五星辰之力。\n#.每个星辰之力拥有#条属性，通过培养可以对属性值进行填充，每次培养会随机对#~#条属性产生加减，属性满时培养不再产生影响。\n#.培养方式分为普通培养和钻石培养，普通培养消耗培养石，钻石培养消耗钻石。钻石培养效率高于普通培养。\n#.培养次数分为一次和十次，培养后点击确认保存培养结果，点击取消不保存培养结果。\n#.培养石可在竞技场商店和远古斗技场商店购买。\n#.使用特殊培养石必定增加属性。 | Star Rules:\n\n#. Star Training unlocks when a hero reaches Purple+# quality. The second, third, fourth and fifth Star Powers unlock at Purple+# and Orange quality.\n#. Each Star Power has # attributes that you fill up through training. Each training randomly raises or lowers #~# attributes. Maxed attributes are no longer affected.\n#. There are two training modes: Normal Training uses Training Stones and Diamond Training uses Diamonds. Diamond Training is more effective.\n#. You can train once or 10 times. After training, tap Confirm to save the result or Cancel to discard it.\n#. Buy Training Stones in the Arena Shop and the Ancient Colosseum Shop.\n#. Special Training Stones always increase attributes. |
| 光辉 | Radiance | 5 / 11 | 光辉意志召唤而出的黄金剑阵，对敌方竖排造成#%伤害，并吸取#%攻击#回合，并降低#点怒气 | A golden sword array summoned by the Radiant Will deals #% damage to an enemy column, drains #% ATK for # turns, and reduces Rage by # |
| 泰坦巨岩 | Titan Rock | 5 / 18 | 收集#个碎片合成泰坦巨岩圣戒 | Collect # shards to craft Titan Bedrock Holy Ring |
| 魔龙 | Dark Dragon | 5 / 10 | 收集#个灵魂石，可以召唤橙色神兽深渊魔龙。同时也是深渊魔龙升星的必备材料。 | Collect # Soul Stones to summon the Orange Divine Beast Abyssal Dragon. Also required to raise the stars of Abyssal Dragon. |
| 护体 | Aegis | 4 / 5 | 圣光护体，正义荣耀，开场无敌和增加血量 | Shielded by holy light in the name of justice. Invincible at battle start and gains bonus HP |
| 神灯 | Genie Lamp | 4 / 14 | 召唤神灯中的无比帅气的神灵，恢复前排队友攻击#%的生命 | Summons the dashingly handsome genie of the lamp, healing front-row allies for #% of ATK |
| 进化 | Evolution | 4 / 6 | ( 当$进化至 | ( When $ evolves to |
| 重生 | Rebirth | 4 / 5 | 骷髅王终于可以重生了，死亡后立即复活 | The Skeleton King can finally be reborn: instantly revives upon death |
| 风暴 | Storm | 4 / 42 | 将冰雪风暴以强大的魔力压缩为利箭，对敌方生命百分比最低的三个单位造成#%伤害，生命百分比越低造成的伤害越高 | Compresses a blizzard into arrows with powerful magic, dealing #% damage to the 3 enemies with the lowest HP%. The lower their HP%, the higher the damage |
| 骷髅 | Skeleton | 4 / 26 | 封面上有骷髅标记，书的周围有黄金镶边修饰 | A skull marks the cover, and the book is trimmed with gold |
| 入侵者 | Invaders | 3 / 5 | 外星入侵者 | Alien Invader |
| 守护女神 | Guardian Goddess | 3 / 27 | 上路守护女神 | Top Lane Guardian Angel |
| 死寂 | Dead Silence | 3 / 5 | 通关公会秘藏：死寂之桥 | Clear Guild Vault: Bridge of Silence |
| 汤圆 | Sweet Rice Dumpling | 3 / 4 | 使用后解锁【香糯汤圆】头像，元宵节专属头像！ | Use to unlock the [Sweet Tangyuan] avatar, exclusive to the Lantern Festival! |
| 诞生 | Birth | 3 / 4 | 与世界一起诞生的上古巨岩，后被天神用来守护神界之门，抵挡魔王入侵 | An ancient boulder born with the world itself, later used by the gods to guard the Gate of the Divine Realm against the Demon Lord's invasion |
| 震撼大地 | Earthshatter | 3 / 4 | 撼地金刚一族世世代代守护的神锤，可以震撼大地 | The divine hammer guarded by the Earthshaker Colossus clan for generations, mighty enough to shake the earth. |
| 二连斩 | Double Slash | 2 / 2 | 使用手上的利器对敌人造成二连斩击，造成#%伤害并降低防御 | Strikes the enemy twice with a keen blade, dealing #% damage and lowering DEF |
| 失踪 | Missing | 2 / 3 | 沉睡谷本是个古战场，在许多年后，附近的人们见此地较为平坦，又紧挨着一片茂密的森林，是个不错的栖息之地，便在沉睡谷上建起了村落，安居乐业。直至有一天，开始有人接连神秘失踪，而无一例外的是，每有人失踪的前一夜，似乎所有人都听到了马蹄声。 | Sleepy Hollow was once an ancient battlefield. Many years later, people nearby found the land fairly flat and bordered by a dense forest, a fine place to settle, so they built a village there and lived in peace. Until one day, people began vanishing one after another. And without fail, on the night before each disappearance, everyone seemed to hear the sound of hoofbeats. |
| 夺魄 | Soulreaver | 2 / 3 | 噬魂夺魄，令恶魔闻风丧胆。射出三支箭，对沿途单位造成#%伤害 | Soul-devouring arrows that strike terror into demons. Fires three arrows, dealing #% damage to all units in their path |
