plugins {
    id("com.android.application")
}

android {
    namespace = "com.jxust.campuswlan"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.jxust.campuswlan"
        minSdk = 28
        targetSdk = 35
        versionCode = 4
        versionName = "1.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
}
