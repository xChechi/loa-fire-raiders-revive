# Chinese text inside images: inventory (23-11-2026)

The stock client has 6,221 PNG files under res/assets. Nothing here was changed; this is the
list for the owner's decision on re-drawing. Files were grouped by path and file name, and each group
was sample-checked with a contact sheet where marked. Groups that are pure art (hero/angel bodies,
skill effects, map tiles, item icons) are left out: no text was seen in them.

Also seen on the 23-11 screenshots but not caught by a name rule: the 注销账号 and 服务器 plates on
the login screen, 胜利 and 联盟EXP on the fight result, 联盟升级 on the level-up dialog, 挑战 on
the challenge button, 总览 and 可装备/无装备 on the hero detail (RoleUIEquipState*.png).

Not exhaustive: the rest of the ui/ tree (about 3,000 files in 100+ feature folders) was not swept
image by image. The one generic folder checked whole, ui/btn, has 2 of 56 files with text (印记,
一键领取); the other buttons are blank plates with the label drawn by the Lua.

Bitmap fonts: the two .fnt files (fight/green_number, fight/red_number) hold 14 glyphs each, digits
and signs only, no Chinese. The 71 *num*.png atlases are digit strips.

| group | files | Chinese text | how checked |
|---|---|---|---|
| hero name images (img/hero/name) | 78 | confirmed | all sampled (10/10) are the hero's Chinese name in gold title type, shown on the hero card (玫瑰骑士 in 05-hero-detail) |
| angel name images (img/angel/name) | 31 | likely | same layout as the hero names; not opened |
| main city buttons (ui/mainSceneImg/mainBtn*, platformCenter, happynewyear) | 32 | confirmed | contact sheet of the folder: every mainBtn* icon has its label (排行榜, 英雄, 探险, ...) baked in |
| title words (name has title/Title, not a background) | 77 | mostly | contact sheet of the first 60: about 45 carry Chinese (阵容设置, 突破成功, 1月签到奖励 ...), the rest are empty ribbons/frames |
| word/text images (name has word/Word/txt/Txt/zi/font) | 12 | confirmed | sampled: 战力:, 战斗结束, 恭喜您过关!; battle_level_up_txt is already English (LEVEL UP!) |
| logo / login | 24 | partly | gameLogin_Bigbg.png carries the 女神联盟 logo; the costStone/discount logos are shop art, not checked |
| class badges (career/carrer/vocation) | 6 | confirmed | 战士/法师/射手 badges (RoleListCarrerBg1-3) and 战/法/射 card seals (roleUICardCarrer1-3) |
| chapter / map names (img/chapter) | 17 | unchecked | chapter banners; likely carry the chapter name |
| stamps (ui/stamp) | 27 | unchecked | stamp/seal art; some may carry characters |
| **total in these groups** | **304** | | |

## Stage 1 re-draw (24-11-2026)

142 images are now re-drawn in English by `py -3.14 -m localise.images` from the reviewed table
`localise/images.toml`, into `data/en/assets/res/assets` (shipped by `client.build_assets`).
Before/after sheets: `docs/screens/en-images-stage1/`.

| group | re-drawn | left out and why |
|---|---|---|
| main city buttons | 31 of 32 | happynewyear.png: the 福 on the lucky bag is decoration, not a label |
| class badges | 6 of 6 | |
| word/text images | 10 of 12 | battle_level_up_txt, vip_word_1: already English |
| title words | 52 of 77 | 25 carry no text (empty ribbons, frames, bars, banners) or are already English (title_double "x2") |
| stamps | 0 of 27 | none carries Chinese: icons, masks, NEW!, VIP11/12, 1-4 dice faces |
| main city activity buttons (activityBtn, not in the name rules) | 28 of 29 | actBtn_3: 抢 inside a red-envelope badge, a different style; left for later |
| seen on screen | 15 | 战力: on the lineup (level_line_img_fight), 注销账号, 服务器 plate, 胜利, 联盟EXP, 联盟升级, 挑战, 总览 x3, 无/可/未装备, 可合成, 以下未激活 |

Not in stage 1: hero and angel name images, chapter banners, logo/login art.

## Stage 2 re-draw (24-11-2026)

115 more images, 257 in all. Before/after sheets: `docs/screens/en-images-stage2/`; on the
emulator: `docs/screens/en-2026-11-24-images2/`.

| group | re-drawn | how / left out and why |
|---|---|---|
| hero name images | 78 of 78 | not listed one by one: `localise.images.name_entries` joins the file's id to `hero_info.name` (346000 to `awaken_info.name`), stock and data/en, so the image says what the game text says |
| angel name images | 31 of 31 | same join on `angel_info.angel_entry`; 9010002 is the Chinese New Year skin of 901000 (SqlManager.lua:485) |
| chapter banners (img/chapter) | 0 of 17 | no text in them: they are the background art of the trial chapter rows (`RecallLevelItem.lua:60`); the name over them is a Lua label from `chapter_info` |
| leftovers seen on screen | 6 | 聊天 Chat (mainSceneMsgBtn), 抢 Grab (actBtn_3), 失败 Defeat (frame 4 of the `ui_eff_battle_lose0` atlas), the captions of battle_end_lost_tip_1-3 |

Where the image and the game table disagree, the English follows the table: 340000 image 主宰,
table 主宰者 (Dominator); 503000 image 潘多拉, table 潘多拉女神 (Pandora). 501000 极寒女神 and
702000 冰霜女神 are both "Frost Goddess" in the translated table, so their images read the same.

Not done: the story speaker 魔法师 is Lua text, not an image. It lives in
`res/assets/story/Story_*.lua` (90 files, 572 `talk=` lines plus their `name=` speakers), and no
localise step reads that folder yet, so the whole story dialogue is still Chinese. That needs a
new text source with translation; it was left out of this image stage. The tip cards' screenshots
keep their tiny baked-in Chinese UI (it is a picture of the old UI); only the captions changed.

## Stage 3 re-draw (24-11-2026)

15 more images, 272 in all. Before/after: `docs/screens/en-images-stage3/logo-login.jpg`.

| group | re-drawn | how / left out and why |
|---|---|---|
| logo / login | 11 of 24 | the ten discount-shop tags N折 ("Pay N0%", so 1折 = "90% OFF") and 佣兵 Mercenary (line-up badge). gameLogin_btn_logoutgame was done in stage 1. The other eleven (girl_logo x2, costStone logo_1-5 and logo_bg_1-2, logo_stone_1-2) are art without text; nslm_logo.png is the logo (below) |
| login plates (not in the 24) | 4 | the 服务器 plate gameLogin_bg and the three login buttons 快速游戏 / 登录账号 / 开始游戏; no Lua loads these four today, re-drawn because they are cheap |
| the logo | 0 of 2 | gameLogin_Bigbg.png (what the login and loading screens load) and nslm_logo.png (no Lua loads it) stay stock until the owner picks a wording: `docs/screens/en-images-stage3/logo-options.jpg` shows the original, "League of Angels" and the placeholder "Fire Raiders" (mocks only) |

## Files per group

### hero name images (img/hero/name) (78)

- `img/hero/name/100000.png`
- `img/hero/name/101000.png`
- `img/hero/name/102000.png`
- `img/hero/name/103000.png`
- `img/hero/name/104000.png`
- `img/hero/name/105000.png`
- `img/hero/name/106000.png`
- `img/hero/name/107000.png`
- `img/hero/name/108000.png`
- `img/hero/name/109000.png`
- `img/hero/name/200000.png`
- `img/hero/name/201000.png`
- `img/hero/name/202000.png`
- `img/hero/name/203000.png`
- `img/hero/name/204000.png`
- `img/hero/name/205000.png`
- `img/hero/name/206000.png`
- `img/hero/name/207000.png`
- `img/hero/name/208000.png`
- `img/hero/name/209000.png`
- `img/hero/name/210000.png`
- `img/hero/name/211000.png`
- `img/hero/name/212000.png`
- `img/hero/name/213000.png`
- `img/hero/name/214000.png`
- `img/hero/name/215000.png`
- `img/hero/name/216000.png`
- `img/hero/name/217000.png`
- `img/hero/name/218000.png`
- `img/hero/name/290000.png`
- `img/hero/name/300000.png`
- `img/hero/name/301000.png`
- `img/hero/name/302000.png`
- `img/hero/name/303000.png`
- `img/hero/name/304000.png`
- `img/hero/name/305000.png`
- `img/hero/name/306000.png`
- `img/hero/name/307000.png`
- `img/hero/name/308000.png`
- `img/hero/name/309000.png`
- `img/hero/name/310000.png`
- `img/hero/name/311000.png`
- `img/hero/name/312000.png`
- `img/hero/name/313000.png`
- `img/hero/name/314000.png`
- `img/hero/name/315000.png`
- `img/hero/name/316000.png`
- `img/hero/name/317000.png`
- `img/hero/name/318000.png`
- `img/hero/name/319000.png`
- `img/hero/name/320000.png`
- `img/hero/name/321000.png`
- `img/hero/name/322000.png`
- `img/hero/name/323000.png`
- `img/hero/name/324000.png`
- `img/hero/name/325000.png`
- `img/hero/name/326000.png`
- `img/hero/name/327000.png`
- `img/hero/name/328000.png`
- `img/hero/name/329000.png`
- `img/hero/name/330000.png`
- `img/hero/name/331000.png`
- `img/hero/name/332000.png`
- `img/hero/name/333000.png`
- `img/hero/name/334000.png`
- `img/hero/name/335000.png`
- `img/hero/name/336000.png`
- `img/hero/name/337000.png`
- `img/hero/name/338000.png`
- `img/hero/name/339000.png`
- `img/hero/name/340000.png`
- `img/hero/name/341000.png`
- `img/hero/name/342000.png`
- `img/hero/name/343000.png`
- `img/hero/name/344000.png`
- `img/hero/name/345000.png`
- `img/hero/name/346000.png`
- `img/hero/name/999000.png`

### angel name images (img/angel/name) (31)

- `img/angel/name/500000.png`
- `img/angel/name/501000.png`
- `img/angel/name/502000.png`
- `img/angel/name/503000.png`
- `img/angel/name/504000.png`
- `img/angel/name/505000.png`
- `img/angel/name/506000.png`
- `img/angel/name/507000.png`
- `img/angel/name/508000.png`
- `img/angel/name/509000.png`
- `img/angel/name/510000.png`
- `img/angel/name/511000.png`
- `img/angel/name/600000.png`
- `img/angel/name/700000.png`
- `img/angel/name/701000.png`
- `img/angel/name/702000.png`
- `img/angel/name/800000.png`
- `img/angel/name/801000.png`
- `img/angel/name/802000.png`
- `img/angel/name/803000.png`
- `img/angel/name/900000.png`
- `img/angel/name/901000.png`
- `img/angel/name/9010002.png`
- `img/angel/name/902000.png`
- `img/angel/name/903000.png`
- `img/angel/name/904000.png`
- `img/angel/name/905000.png`
- `img/angel/name/906000.png`
- `img/angel/name/907000.png`
- `img/angel/name/908000.png`
- `img/angel/name/909000.png`

### main city buttons (ui/mainSceneImg/mainBtn*, platformCenter, happynewyear) (32)

- `ui/mainSceneImg/happynewyear.png`
- `ui/mainSceneImg/mainBtnBaoGuo.png`
- `ui/mainSceneImg/mainBtnBaoShi.png`
- `ui/mainSceneImg/mainBtnChongZhi.png`
- `ui/mainSceneImg/mainBtnFuBen.png`
- `ui/mainSceneImg/mainBtnFuWen.png`
- `ui/mainSceneImg/mainBtnFuYou.png`
- `ui/mainSceneImg/mainBtnGongHui.png`
- `ui/mainSceneImg/mainBtnGuildList.png`
- `ui/mainSceneImg/mainBtnHaoYou.png`
- `ui/mainSceneImg/mainBtnHuoDong.png`
- `ui/mainSceneImg/mainBtnJingJi.png`
- `ui/mainSceneImg/mainBtnNvShen.png`
- `ui/mainSceneImg/mainBtnQianDao.png`
- `ui/mainSceneImg/mainBtnRank.png`
- `ui/mainSceneImg/mainBtnRenWu.png`
- `ui/mainSceneImg/mainBtnShangDian.png`
- `ui/mainSceneImg/mainBtnShenGe.png`
- `ui/mainSceneImg/mainBtnShenHun.png`
- `ui/mainSceneImg/mainBtnShenQi.png`
- `ui/mainSceneImg/mainBtnShenShou.png`
- `ui/mainSceneImg/mainBtnShiLian.png`
- `ui/mainSceneImg/mainBtnStarHun.png`
- `ui/mainSceneImg/mainBtnXingChen.png`
- `ui/mainSceneImg/mainBtnXunLian.png`
- `ui/mainSceneImg/mainBtnYangCheng.png`
- `ui/mainSceneImg/mainBtnYinJi.png`
- `ui/mainSceneImg/mainBtnYinXiong.png`
- `ui/mainSceneImg/mainBtnYingXiong.png`
- `ui/mainSceneImg/mainBtnYouJian.png`
- `ui/mainSceneImg/mainBtnZhanBu.png`
- `ui/mainSceneImg/platformCenter.png`

### title words (name has title/Title, not a background) (77)

- `ui/angelAdvance/suc_title.png`
- `ui/angelTrainEnemySelectTitle.png`
- `ui/angelTrainRankTitle.png`
- `ui/angel_circle_fight_title.png`
- `ui/angel_new_title.png`
- `ui/angel_skill_icon_title_1.png`
- `ui/angel_skill_icon_title_2.png`
- `ui/arenaMainTitle.png`
- `ui/arena_new_rank_title.png`
- `ui/bagInfoTitle1.png`
- `ui/bagInfoTitle2.png`
- `ui/bagInfoTitle3.png`
- `ui/border/title_12.png`
- `ui/crossServerArena/crossServer_attack_title.png`
- `ui/crossServerArena/crossServer_defend_title.png`
- `ui/crossServerPVP/report_title_bg_lose.png`
- `ui/crossServerPVP/report_title_bg_win.png`
- `ui/devilTry/devilTryRankTitle.png`
- `ui/donate/title.png`
- `ui/flop_title.png`
- `ui/group_info_headTitle1.png`
- `ui/group_info_headTitle2.png`
- `ui/guildGve/selectedui/chapter_selectTitle.png`
- `ui/guildGve/selectedui/chapter_selectTitle1.png`
- `ui/gve_title.png`
- `ui/img/item_rank_titleBmp.png`
- `ui/img/title_double.png`
- `ui/legendsStore/legendsTitleTop.png`
- `ui/legendsStore/legendstitle.png`
- `ui/levelUI/currentTitle.png`
- `ui/levelUI/firstTitle.png`
- `ui/line_title_txt.png`
- `ui/npc_tower_title.png`
- `ui/recall_eff_title.png`
- `ui/roleAwake/titleBg_1.png`
- `ui/roleAwake/titleBg_2.png`
- `ui/roleBreak/suc_title.png`
- `ui/scoreShop/title.png`
- `ui/scoreShop/title_2.png`
- `ui/sevenAvtivity/sevenAct_hero_title.png`
- `ui/seven_img_title.png`
- `ui/shopTitle.png`
- `ui/sign_title_text1.png`
- `ui/sign_title_text10.png`
- `ui/sign_title_text11.png`
- `ui/sign_title_text12.png`
- `ui/sign_title_text2.png`
- `ui/sign_title_text3.png`
- `ui/sign_title_text4.png`
- `ui/sign_title_text5.png`
- `ui/sign_title_text6.png`
- `ui/sign_title_text7.png`
- `ui/sign_title_text8.png`
- `ui/sign_title_text9.png`
- `ui/sign_title_text_VIP.png`
- `ui/sociaty/banneretUpTitle.png`
- `ui/sociaty/sociaty_list_box_title_bg_1.png`
- `ui/sociaty/sociaty_list_box_title_bg_2.png`
- `ui/sociaty/sociaty_list_box_title_bg_3.png`
- `ui/sociaty/sociaty_list_box_title_bg_4.png`
- `ui/sociatyBattle/BossEnter/title_flag.png`
- `ui/sociatyBattle/rank/rank_title_1.png`
- `ui/sociatyBattle/robmine/mine_title.png`
- `ui/sociatyBattle/situation/title.png`
- `ui/sociatytrainTitle.png`
- `ui/sociay_rank_title1.png`
- `ui/sociay_rank_title2.png`
- `ui/sociay_rank_title3.png`
- `ui/task_small_title.png`
- `ui/tavern_title.png`
- `ui/title_big.png`
- `ui/titlebar.png`
- `ui/top/top_title.png`
- `ui/topArena/top_arena_rank_title_1.png`
- `ui/topArena/top_arena_rank_title_2.png`
- `ui/topArena/top_arena_rank_title_3.png`
- `ui/vip_gift_text_title.png`

### word/text images (name has word/Word/txt/Txt/zi/font) (12)

- `ui/arena_ability_word.png`
- `ui/battle_end_coin_try_txt.png`
- `ui/battle_end_pass_level_txt.png`
- `ui/battle_level_up_txt.png`
- `ui/guildGve/recommand_ability_txt.png`
- `ui/guild_party_join_txt.png`
- `ui/mojunStruck/recomonedHeroTxt.png`
- `ui/openFundAct/tipTxt.png`
- `ui/seven_txt_day.png`
- `ui/seven_txt_th.png`
- `ui/train_box_unlock_txt.png`
- `ui/vip_word_1.png`

### logo / login (24)

- `ui/angelPeng/girl_logo.png`
- `ui/costStone/logo_1.png`
- `ui/costStone/logo_2.png`
- `ui/costStone/logo_3.png`
- `ui/costStone/logo_4.png`
- `ui/costStone/logo_5.png`
- `ui/costStone/logo_bg_1.png`
- `ui/costStone/logo_bg_2.png`
- `ui/discountshop/discountLogo.png`
- `ui/discountshop/discountLogo_1.png`
- `ui/discountshop/discountLogo_2.png`
- `ui/discountshop/discountLogo_3.png`
- `ui/discountshop/discountLogo_4.png`
- `ui/discountshop/discountLogo_5.png`
- `ui/discountshop/discountLogo_6.png`
- `ui/discountshop/discountLogo_7.png`
- `ui/discountshop/discountLogo_8.png`
- `ui/discountshop/discountLogo_9.png`
- `ui/friendschat/girl_logo.png`
- `ui/gameLogin_btn_logoutgame.png`
- `ui/gemstone/logo_stone_1.png`
- `ui/gemstone/logo_stone_2.png`
- `ui/kf_soldier_logo.png`
- `ui/nslm_logo.png`

### class badges (career/carrer/vocation) (6)

- `ui/nslm_rolePanelUI/RoleListCarrerBg1.png`
- `ui/nslm_rolePanelUI/RoleListCarrerBg2.png`
- `ui/nslm_rolePanelUI/RoleListCarrerBg3.png`
- `ui/nslm_rolePanelUI/card/roleUICardCarrer1.png`
- `ui/nslm_rolePanelUI/card/roleUICardCarrer2.png`
- `ui/nslm_rolePanelUI/card/roleUICardCarrer3.png`

### chapter / map names (img/chapter) (17)

- `img/chapter/100010.png`
- `img/chapter/100020.png`
- `img/chapter/100030.png`
- `img/chapter/100040.png`
- `img/chapter/100050.png`
- `img/chapter/100060.png`
- `img/chapter/100070.png`
- `img/chapter/100080.png`
- `img/chapter/100090.png`
- `img/chapter/100100.png`
- `img/chapter/100110.png`
- `img/chapter/100120.png`
- `img/chapter/100130.png`
- `img/chapter/100140.png`
- `img/chapter/100150.png`
- `img/chapter/100160.png`
- `img/chapter/100170.png`

### stamps (ui/stamp) (27)

- `ui/stamp/advanceBg_1.png`
- `ui/stamp/advanceBg_2.png`
- `ui/stamp/advanceBg_3.png`
- `ui/stamp/backBtn.png`
- `ui/stamp/exIcon.png`
- `ui/stamp/heroListViewMask.png`
- `ui/stamp/heroSelectImg.png`
- `ui/stamp/newIcon.png`
- `ui/stamp/rightMask.png`
- `ui/stamp/scrollMask.png`
- `ui/stamp/setBg.png`
- `ui/stamp/signetImgs.png`
- `ui/stamp/signetMask.png`
- `ui/stamp/stampIcon.png`
- `ui/stamp/tab_1.png`
- `ui/stamp/tab_10.png`
- `ui/stamp/tab_11.png`
- `ui/stamp/tab_12.png`
- `ui/stamp/tab_2.png`
- `ui/stamp/tab_3.png`
- `ui/stamp/tab_4.png`
- `ui/stamp/tab_5.png`
- `ui/stamp/tab_6.png`
- `ui/stamp/tab_7.png`
- `ui/stamp/tab_8.png`
- `ui/stamp/tab_9.png`
- `ui/stamp/titleBg.png`
