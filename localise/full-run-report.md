# English localisation: full run (effort medium)

Model `claude-opus-5-5`, normal Messages API, batches of up to 40 lines / 4000 chars. Order: hero and angel names, the other names with the hero/angel glossary, then all other text with the full glossary. Medium-effort rows from the sample were reused, not re-paid.

## Counts

| pass | templates | translated | missing after retry |
|---|---|---|---|
| names-1 | 113 | 113 | 0 |
| names-2 | 2,772 | 2,772 | 0 |
| text | 8,198 | 8,158 | 40 |
| total | 11,083 | 11,043 | 40 |

## Tokens and cost

| run | calls | rejected calls | input | output | cache write | cache read | API time min | USD |
|---|---|---|---|---|---|---|---|---|
| full (all) | 275 | 2 | 235,369 | 365,448 | 64,053 | 12,474,204 | 51 | 11.0655 |
| sample (medium) | 6 | 0 | 4,189 | 6,703 | 1,856 | 6,926 | 1 | 0.1615 |

All API spend on this project so far (both sample efforts + full run): $11.3607.

## Templates missing after retry

- text (stage/story text): `强力后排攻击射手`
- text (stage/story text): `强力控制`
- text (stage/story text): `强力的全体伤害型射手`
- text (stage/story text): `强力肉盾，可免疫控制和控制敌人`
- text (stage/story text): `强力范围攻击的冰龙`
- text (stage/story text): `强力范围攻击的魔龙`
- text (stage/story text): `当时我手里只有一把父亲为我做的弓。整整#天！躲避野兽的攻击，寻找食物，我能做的就是想尽一切办法让自己不被野兽吃掉。`
- text (stage/story text): `很久以前，驱魔一族英俊潇洒、风流倜傥，是万千少女心中的向往。然而他们为了获得力量，毅然决然的放弃了自己的颜值，想要靠驱魔才华征服世界！`
- text (stage/story text): `很快你们登上了凯旋高塔，只要通关这里，这次的远征便将结束。其他的事以后再说吧，哈哈！`
- text (stage/story text): `很明显，这里曾是关押囚犯的地方，但现在这些人和看守的怪物都去了哪了？`
- text (stage/story text): `忐忑地从毒沼旁走过，突然从中冒出一只巨口的虫子，怎么办`
- text (stage/story text): `忽然间狂风大作，天空中的太阳以肉眼可见的速度迅速黑暗了下去。一群猩红的蝙蝠飞来，带来了一个南瓜？不，是顶着南瓜的怪物！`
- text (stage/story text): `忽然间神殿剧烈震动了起来，中心法阵放射出耀眼的光芒，紧接着地狱烈焰般的红炎冲天而上，仿佛着一个恶魔即将重生`
- text (stage/story text): `恐怖的气息四面袭来，你已无暇分辨，应战是唯一的选择。`
- text (stage/story text): `恐惧降临！`
- text (stage/story text): `恭喜您成功加入了公会 |，快去公会频道和公会小伙伴打个招呼吧！`
- text (stage/story text): `恭喜您被会长提升为 |`
- text (stage/story text): `恭喜！您已接任了会长职位！`
- text (stage/story text): `恶作剧描述`
- text (stage/story text): `恶魔猎人描述`
- text (stage/story text): `恶魔，让人闻风丧胆的名字，所到之处皆涂炭生灵。而她，却以猎杀恶魔为职，放弃了情感。`
- text (stage/story text): `您从|的|号资源点提前撤退了，获得以下奖励：`
- text (stage/story text): `您在|的|号资源点今日开采完毕，获得以下奖励：`
- text (stage/story text): `您在|的|号资源点被来自|公会的|掠夺了！\n     您被掠夺了|资源、|功勋，获得了以下奖励：`
- text (stage/story text): `您在|的|号资源点被来自|公会的|攻击了！\n     您成功击退了对手，获得了功勋奖励！`
- text (stage/story text): `您在|的资源点已开采完毕。获得了以下奖励：`
- text (stage/story text): `您在|的资源点被来自|公会的|掠夺了！您失去了|个|、|功勋`
- text (stage/story text): `您在今日的海岛争霸中累计获得功勋值|点，排行第|！请领取您的奖励：`
- text (stage/story text): `您在今日的海岛激战中累计获得功勋值|点，排行第|！请领取您的奖励：`
- text (stage/story text): `您在本赛季的海岛激战中累计获得功勋值|点，排行第|！请领取您的奖励：`
- text (stage/story text): `您完成了一个成就，让我们马上去提交吧！`
- text (stage/story text): `您派出的雇佣兵已追随您离开了公会，这是他们驻守营地的收入：`
- text (stage/story text): `您的公会|在今日的海岛争霸中累计获得功勋值|点，排行第|！为了表彰您的贡献，以下是您的奖励：`
- text (stage/story text): `您的公会|在今日的海岛激战中累计获得功勋值|点，排行第|！为了表彰您的贡献，以下是您的奖励：`
- text (stage/story text): `您的公会|在今日的海岛激战结算时的资源占有度为|，排行第|！为了表彰您的贡献，以下是您的奖励：`
- text (stage/story text): `您的公会|在本赛季的海岛激战中累计获得功勋值|点，排行第|！为了表彰您的贡献，以下是您的奖励：`
- text (stage/story text): `您的公会|的全体成员对魔王造成了累计|点的伤害，苦战后终于击退魔王大军！为了表彰您的贡献，以下是您的奖励：`
- text (stage/story text): `您被会长降职为 |`
- text (stage/story text): `您被移出了公会 |`
- text (stage/story text): `悬崖上隆起的高地，登上去就能看到这片区域的全貌。`

Failure reasons per batch (last attempt):

- text: line 28: placeholders differ (missing {}, extra {'#': 1}); line 29: placeholders differ (missing {}, extra {'#': 1}); line 30: placeholders differ (missing {}, extra {'#': 1}); line 33: placeholders differ (missing {}, extra {'#': 1}); line 34: placeholders differ (missing {}, extra {'#': 1}); line 35: placeholders differ (missing {}, extra {'#': 1}); line 36: placeholders differ (missing {}, extr

## Glossary consistency (top 30)

86 glossary names have at least one non-name translation that contains the Chinese name but not its glossary English (case-insensitive substring check; names under 2 chars or with `#` skipped). Some are inflections or plurals, not real mismatches.

| Chinese name | glossary English | mismatches / uses | example text | its English |
|---|---|---|---|---|
| 觉醒 | Awakening | 147 / 180 | %s未达到本次觉醒条件 | %s does not meet the requirements for this Awaken |
| 精灵 | Elf | 62 / 83 | “绿精灵套装”之一 | Part of the "Green Sprite Set" |
| 血族 | Vampires | 20 / 32 | 血族王子#技能免疫物理 | Vampire Prince Skill # Physical Immunity |
| 圣灵 | Holy Spirit | 18 / 28 | 圣灵守护者觉醒技能加免伤 | Holy Guardian Awaken Skill DMG Reduction Up |
| 利刃 | Keen Edge | 12 / 12 | 魔之利刃 | Demon Blade |
| 驱魔 | Exorcism | 11 / 12 | 可合成驱魔披风。 | Used to craft Exorcist Cloak. |
| 光之继承 | Legacy of Light | 10 / 11 | 护佑功能规则说明:\n#.护佑功能允许联盟队长将已培养英雄和女神放至指定的护佑勋章中，来为对应类型的英雄增加属性。比如战之斗魂勋章要求狂暴之爪、小女巫、光之继承者和恶魔猎人，只要玩家将这#位英雄上阵，并可以为所有战士职业英雄增加攻击相关的属性，而不是为这#位英雄增加属性\n#.英雄的类型目前分为职业和性别两种\n#.勋章会随着联盟等级分批开启。\n#.每个勋章初期只会开放#个女神位+#个英雄位，其余的#个英雄位需要玩家在公会秘藏玩法中积攒栏位解锁符来开启。\n#.英雄和女神的培养程度会影响各自的评分，评分会影响最终所能够增加的属性（评分并不完全通过总战力计算，每个能力点能提供的评分各不相同）。\n      影响英雄评分的元素:\n            等级、星级、装备、技能、符文\n      影响女神评分的元素:\n            等级、星级、技能、光环\n | Blessing Rules:\n#. Blessing lets the Alliance Captain place trained Heroes and Angels in specific Blessing Medals to boost stats for Heroes of the matching type. For example, the War Spirit Medal requires Frenzy Claw, Little Witch, Heir of Light and Demon Hunter. Once the player deploys these # Heroes, all Warrior Heroes gain attack-related stats, rather than only these # Heroes.\n#. Hero types are currently divided by class and gender.\n#. Medals unlock in batches as Alliance Level rises.\n#. Each Medal initially opens only # Angel slot + # Hero slots; the remaining # Hero slots are unlocked with Slot Unlock Charms collected in the Guild Vault.\n#. How well Heroes and Angels are trained affects their Rating, and Rating determines the final stat bonus (Rating is not based solely on total Power; each attribute point contributes a different amount).\n      Factors affecting Hero Rating:\n            Level, Stars, Gear, Skills, Runes\n      Factors affecting Angel Rating:\n            Level, Stars, Skills, Aura\n |
| 毁灭 | Destruction | 10 / 13 | 炎龙烈阳具有强大的毁灭之力，天神为了保护使用者用万龙之鳞打造的圣戒 | Dragonsun wields immense destructive power. To protect its wielder, the gods forged this holy ring from the scales of a myriad dragons. |
| 复仇 | Revenge | 9 / 11 | #级的复仇女神光环# | Lv.# Nemesis Aura # |
| 战争机器 | War Machine | 9 / 9 | 战争机器人医疗形态buff# | War Mech Medic Form Buff # |
| 泰坦巨岩 | Titan Rock | 9 / 18 | 收集#个碎片合成泰坦巨岩 | Collect # Shards to forge Titan Boulder |
| 烈焰之怒 | Wrath of Flames | 8 / 10 | 收集#个碎片合成烈焰之怒戒指 | Collect # shards to craft Ring of Blazing Fury |
| 星辰 | Stars | 6 / 23 | 星辰规则说明:\n\n#.每个英雄品质达到紫色+#开启星辰培养，品质达到紫色+#、橙色时开启第二、第三、第四、第五星辰之力。\n#.每个星辰之力拥有#条属性，通过培养可以对属性值进行填充，每次培养会随机对#~#条属性产生加减，属性满时培养不再产生影响。\n#.培养方式分为普通培养和钻石培养，普通培养消耗培养石，钻石培养消耗钻石。钻石培养效率高于普通培养。\n#.培养次数分为一次和十次，培养后点击确认保存培养结果，点击取消不保存培养结果。\n#.培养石可在竞技场商店和远古斗技场商店购买。\n#.使用特殊培养石必定增加属性。 | Star Rules:\n\n#. Star Training unlocks when a hero reaches Purple+# quality. The second, third, fourth and fifth Star Powers unlock at Purple+# and Orange quality.\n#. Each Star Power has # attributes that you fill up through training. Each training randomly raises or lowers #~# attributes. Maxed attributes are no longer affected.\n#. There are two training modes: Normal Training uses Training Stones and Diamond Training uses Diamonds. Diamond Training is more effective.\n#. You can train once or 10 times. After training, tap Confirm to save the result or Cancel to discard it.\n#. Buy Training Stones in the Arena Shop and the Ancient Colosseum Shop.\n#. Special Training Stones always increase attributes. |
| 光辉 | Radiance | 5 / 11 | 光辉意志召唤而出的黄金剑阵，对敌方竖排造成#%伤害，并吸取#%攻击#回合，并降低#点怒气 | A golden sword array summoned by the Radiant Will deals #% damage to an enemy column, drains #% ATK for # turns, and reduces Rage by # |
| 魔龙 | Dark Dragon | 5 / 9 | 收集#个灵魂石，可以召唤橙色神兽深渊魔龙。同时也是深渊魔龙升星的必备材料。 | Collect # Soul Stones to summon the Orange Divine Beast Abyssal Dragon. Also required to raise the stars of Abyssal Dragon. |
| 奥创灭世 | Ultron's Apocalypse | 4 / 4 | 奥创灭世A技能三#描述 | Ultron Apocalypse A Skill 3# Description |
| 护体 | Aegis | 4 / 5 | 圣光护体，正义荣耀，开场无敌和增加血量 | Shielded by holy light in the name of justice. Invincible at battle start and gains bonus HP |
| 神灯 | Genie Lamp | 4 / 14 | 召唤神灯中的无比帅气的神灵，恢复前排队友攻击#%的生命 | Summons the dashingly handsome genie of the lamp, healing front-row allies for #% of ATK |
| 血族末裔 | Last of the Vampires | 4 / 13 | 打开可获得：#金币、大经验药水*#、灵魂石(血族末裔)*#~#、功勋*# | Open to receive: # Gold, Large EXP Potion*#, Soul Stone (Vampire Scion)*#~#, Merit*# |
| 进化 | Evolution | 4 / 6 | ( 当$进化至 | ( When $ evolves to |
| 风暴 | Storm | 4 / 42 | 将冰雪风暴以强大的魔力压缩为利箭，对敌方生命百分比最低的三个单位造成#%伤害，生命百分比越低造成的伤害越高 | Compresses a blizzard into arrows with powerful magic, dealing #% damage to the 3 enemies with the lowest HP%. The lower their HP%, the higher the damage |
| 骷髅 | Skeleton | 4 / 26 | 封面上有骷髅标记，书的周围有黄金镶边修饰 | A skull marks the cover, and the book is trimmed with gold |
| 入侵者 | Invaders | 3 / 5 | 外星入侵者 | Alien Invader |
| 守夜人 | Night Watchman | 3 / 13 | 守夜人觉醒的必备材料。 | Essential material to Awaken Nightwatcher. |
| 守护女神 | Guardian Goddess | 3 / 27 | 上路守护女神 | Top Lane Guardian Angel |
| 死寂 | Dead Silence | 3 / 5 | 通关公会秘藏：死寂之桥 | Clear Guild Vault: Bridge of Silence |
| 汤圆 | Sweet Rice Dumpling | 3 / 4 | 使用后解锁【香糯汤圆】头像，元宵节专属头像！ | Use to unlock the [Sweet Tangyuan] avatar, exclusive to the Lantern Festival! |
| 诞生 | Birth | 3 / 4 | 与世界一起诞生的上古巨岩，后被天神用来守护神界之门，抵挡魔王入侵 | An ancient boulder born with the world itself, later used by the gods to guard the Gate of the Divine Realm against the Demon Lord's invasion |
| 重生 | Rebirth | 3 / 4 | 骷髅王终于可以重生了，死亡后立即复活 | The Skeleton King can finally be reborn: instantly revives upon death |
| 震撼大地 | Earthshatter | 3 / 4 | 撼地金刚一族世世代代守护的神锤，可以震撼大地 | The divine hammer guarded by the Earthshaker Colossus clan for generations, mighty enough to shake the earth. |
