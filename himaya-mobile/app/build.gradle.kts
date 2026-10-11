plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.himaya.agent"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.himaya.agent"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Kotlin stdlib
    implementation("org.jetbrains.kotlin:kotlin-stdlib:2.0.20")
    // OkHttp for HTTP client
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // Lifecycle awareness
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.lifecycle:lifecycle-livedata-ktx:2.7.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.7.0")
    // Coroutines for async work
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    // Coil for image loading
    implementation("io.coil-kt:coil:2.4.0")
    // AndroidX Core & AppCompat
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    // MediaProjection for screen capture
    implementation("androidx.media:media:1.6.0")
}