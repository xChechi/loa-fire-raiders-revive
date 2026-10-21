plugins {
    id("com.android.application")
}

android {
    namespace = "bg.stefan.loa"
    compileSdk = 36

    defaultConfig {
        applicationId = "bg.stefan.loa"
        minSdk = 21
        targetSdk = 33
        versionCode = 1
        versionName = "1.0.0.5"
        ndk {
            abiFilters += "armeabi-v7a"
        }
    }

    // 449 MB of res/ plus 17 MB of scripts/: compressing it doubles the
    // packaging time for no gain, the engine reads these through
    // CCFileUtils::getFileData anyway.
    androidResources {
        noCompress += listOf("db", "zip", "pb", "proto", "lua", "mp3", "ogg",
                             "png", "jpg", "plist", "csb", "ExportJson", "txt")
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true // android:extractNativeLibs="true"
        }
    }

    signingConfigs {
        create("release") {
            val dir = File(System.getProperty("user.home"), ".loa-keystore")
            val pw = File(dir, "password.txt")
            storeFile = File(dir, "loa.jks")
            storePassword = if (pw.exists()) pw.readText().trim() else ""
            keyAlias = "loa"
            keyPassword = storePassword
        }
    }

    buildTypes {
        getByName("debug") {
            isMinifyEnabled = false
            isDebuggable = true
        }
        getByName("release") {
            isMinifyEnabled = false
            isDebuggable = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = false
    }
}
