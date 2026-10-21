package com.uuzu.nslm;

import android.util.Log;

/** Generated stub: see client/gen_luaj_stubs.py. Do not edit by hand. */
public class JavaSuperSDKManager {

    public static void checkVersion() {
        Log.i("LOAStub", "JavaSuperSDKManager.checkVersion");
    }

    public static void closeEmbedUrl() {
        Log.i("LOAStub", "JavaSuperSDKManager.closeEmbedUrl");
    }

    public static void closeFloatWindow() {
        Log.i("LOAStub", "JavaSuperSDKManager.closeFloatWindow");
    }

    public static void enterCustomerService() {
        Log.i("LOAStub", "JavaSuperSDKManager.enterCustomerService");
    }

    public static void enterPlatformCenter() {
        Log.i("LOAStub", "JavaSuperSDKManager.enterPlatformCenter");
    }

    public static void exitSDK() {
        Log.i("LOAStub", "JavaSuperSDKManager.exitSDK");
    }

    public static String getDeviceId() {
        Log.i("LOAStub", "JavaSuperSDKManager.getDeviceId");
        return "LOA-HOME-0001";
    }

    public static String getPlatformConfigByName(String arg0, String arg1) {
        Log.i("LOAStub", "JavaSuperSDKManager.getPlatformConfigByName");
        return arg1;
    }

    public static boolean hasFloatWindow() {
        Log.i("LOAStub", "JavaSuperSDKManager.hasFloatWindow");
        return false;
    }

    public static void initSDK() {
        Log.i("LOAStub", "JavaSuperSDKManager.initSDK");
    }

    public static void login() {
        Log.i("LOAStub", "JavaSuperSDKManager.login");
    }

    public static void logout() {
        Log.i("LOAStub", "JavaSuperSDKManager.logout");
    }

    public static void lua_setCallBack(int arg0) {
        Log.i("LOAStub", "JavaSuperSDKManager.lua_setCallBack");
    }

    public static void lua_setGameServers(int arg0) {
        Log.i("LOAStub", "JavaSuperSDKManager.lua_setGameServers");
    }

    public static void lua_setOnCheckVersionCallBack(int arg0) {
        Log.i("LOAStub", "JavaSuperSDKManager.lua_setOnCheckVersionCallBack");
    }

    public static void lua_setOnInitCallBack(int arg0) {
        Log.i("LOAStub", "JavaSuperSDKManager.lua_setOnInitCallBack");
    }

    public static void lua_setOnLoginPlatformCallBack(int arg0) {
        Log.i("LOAStub", "JavaSuperSDKManager.lua_setOnLoginPlatformCallBack");
    }

    public static void lua_setOnLogoutCallBack(int arg0) {
        Log.i("LOAStub", "JavaSuperSDKManager.lua_setOnLogoutCallBack");
    }

    public static void onGameEvent(String arg0) {
        Log.i("LOAStub", "JavaSuperSDKManager.onGameEvent");
    }

    public static void openEmbedUrl(String arg0, int arg1, int arg2, int arg3, int arg4) {
        Log.i("LOAStub", "JavaSuperSDKManager.openEmbedUrl");
    }

    public static void openFloatWindow(int arg0, int arg1) {
        Log.i("LOAStub", "JavaSuperSDKManager.openFloatWindow");
    }

    public static void openForum() {
        Log.i("LOAStub", "JavaSuperSDKManager.openForum");
    }

    public static void openGMStore(String arg0) {
        Log.i("LOAStub", "JavaSuperSDKManager.openGMStore");
    }

    public static void pay(int arg0, String arg1, String arg2, String arg3, String arg4, String arg5, int arg6) {
        Log.i("LOAStub", "JavaSuperSDKManager.pay");
    }

    public static void setGameData(String arg0, int arg1) {
        Log.i("LOAStub", "JavaSuperSDKManager.setGameData");
    }

    // skipped showAlert: malformed JNI signature '(Ljava/lang/String)V' in the stock Lua

}
