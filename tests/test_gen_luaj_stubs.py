from pathlib import Path

from client.gen_luaj_stubs import java_decl, render, scan

STOCK_SCRIPTS = Path(".stock/assets/scripts")


def test_java_decl_parses_a_jni_signature() -> None:
    assert java_decl("()V") == ([], "void")
    assert java_decl("(Ljava/lang/String;I)V") == (["String", "int"], "void")
    assert java_decl("()Ljava/lang/String;") == ([], "String")
    assert java_decl("()Z") == ([], "boolean")
    assert java_decl("(II)V") == (["int", "int"], "void")
    assert java_decl(
        "(ILjava/lang/String;Ljava/lang/String;Ljava/lang/String;"
        "Ljava/lang/String;Ljava/lang/String;I)V"
    ) == (["int", "String", "String", "String", "String", "String", "int"], "void")


def test_java_decl_rejects_the_malformed_stock_signature() -> None:
    # sdk/LuaSuperSDKManager.lua line 408 writes "(Ljava/lang/String)V": no
    # trailing semicolon, so the JNI lookup can never succeed. Skip, do not guess.
    assert java_decl("(Ljava/lang/String)V") is None


def test_scan_finds_every_class_lua_calls() -> None:
    found = scan(STOCK_SCRIPTS)
    assert set(found) >= {
        "com/uuzu/nslm/JavaSuperSDKManager",
        "com/uuzu/nslm/JavaComSDKManager",
        "com.uuzu.nslm.Nslm",
        "com/uuzu/nslm/Nslm",
    }
    sup = found["com/uuzu/nslm/JavaSuperSDKManager"]
    assert sup["lua_setCallBack"] == ["(I)V"]
    assert sup["checkVersion"] == ["()V"]
    assert sup["login"] == ["()V"]
    assert sup["setGameData"] == ["(Ljava/lang/String;I)V"]
    assert sup["getDeviceId"] == ["()Ljava/lang/String;"]
    assert sup["hasFloatWindow"] == ["()Z"]
    assert sup["openFloatWindow"] == ["(II)V"]
    assert sup["openEmbedUrl"] == ["(Ljava/lang/String;IIII)V"]
    assert sup["getPlatformConfigByName"] == [
        "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;"
    ]
    assert found["com.uuzu.nslm.Nslm"]["getConnectionStatus"] == ["()I"]
    assert found["com.uuzu.nslm.Nslm"]["stopPlaying"] == ["()V"]


def test_scan_keeps_every_overload_of_a_method() -> None:
    found = scan(STOCK_SCRIPTS)
    com = found["com/uuzu/nslm/JavaComSDKManager"]
    assert "(Ljava/lang/String;)V" in com["getGameServers"]
    assert "()V" in com["getGameServers"]


def test_render_emits_the_constant_device_id() -> None:
    src = render(
        "com/uuzu/nslm/JavaSuperSDKManager", {"getDeviceId": ["()Ljava/lang/String;"]}
    )
    assert "package com.uuzu.nslm;" in src
    assert "public class JavaSuperSDKManager" in src
    assert 'return "LOA-HOME-0001";' in src


def test_render_returns_the_default_for_config_lookups() -> None:
    src = render(
        "com/uuzu/nslm/JavaSuperSDKManager",
        {
            "getPlatformConfigByName": [
                "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;"
            ]
        },
    )
    assert "return arg1;" in src


def test_render_skips_a_malformed_signature_with_a_comment() -> None:
    # The real case: LuaSuperSDKManager.lua line 408 calls showAlert with
    # "(Ljava/lang/String)V".
    src = render(
        "com/uuzu/nslm/JavaSuperSDKManager", {"showAlert": ["(Ljava/lang/String)V"]}
    )
    assert "// skipped showAlert" in src
    assert "public static void showAlert" not in src
