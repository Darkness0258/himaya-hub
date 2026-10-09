@rem Gradle start up script for Windows
@rem
@rem Created by Gradle
@rem
@if "%DEBUG%" == "" @set DEBUG=off
@if "%STEPVERBOSE%" == "" @set STEPVERBOSE=off

@rem Set local scope for the variables with windows NT shell
if "%OS%"=="Windows_NT" setlocal

set DIRNAME=%~dp0
if "%DIRNAME%" == "" set DIRNAME=.
set APP_BASE_NAME=%~n0
set APP_HOME=%DIRNAME%

@rem Add default JVM options here. You can also use JAVA_OPTS and GRADLE_OPTS to pass JVM options to this script.
set DEFAULT_JVM_OPTS="-Xmx64m" "-Xms64m"

@rem Find java.exe
if defined JAVA_HOME goto findJavaFromJavaHome

set JAVA_EXE=java.exe
%JAVA_EXE% -version >NUL 2>&1
if "%ERRORLEVEL%" == "0" goto init

echo.
echo ERROR: JAVA_HOME is not set and no 'java' command could be found in your PATH.
echo.
echo Please set the JAVA_HOME variable in your environment to match the
echo location of your Java installation.
goto fail

:findJavaFromJavaHome
set JAVA_HOME=%JAVA_HOME:"=%
set JAVA_EXE=%JAVA_HOME%/bin/java.exe

if exist "%JAVA_EXE%" goto init

echo.
echo ERROR: JAVA_HOME is set to an invalid directory: %JAVA_HOME%
echo.
echo Please set the JAVA_HOME variable in your environment to match the
echo location of your Java installation.
goto fail

:init
@rem Get command-line arguments, handling Windows variants

if not "%OS%" == "Windows_NT" goto win9xME_args

:win9xME_args
@rem Slurp the command line arguments
set CMD_LINE_ARGS=
if "%1" == "--debug" goto debug
if "%1" == "--info" goto info
if "%1" == "--quiet" goto quiet
if "%1" == "--verbose" goto verbose
if "%1" == "--version" goto version
if "%1" == "--no-daemon" goto noDaemon
if "%1" == "--stop" goto stop
if "%1" == "--continue" goto continue
if "%1" == "--reject-service-loaders" goto rejectServiceLoaders
if "%1" == "--configure-on-demand" goto configureOnDemand
if "%1" == "--build-cache" goto buildCache
if "%1" == "--no-build-cache" goto noBuildCache
if "%1" == "--offline" goto offline
if "%1" == "--refresh-dependencies" goto refreshDependencies
if "%1" == "--await" goto await
if "%1" == "--scan" goto scan
if "%1" == "--no-configuration-cache" goto noConfigurationCache
if "%1" == "--debug-jni" goto debugJni
if "%1" == "--interactive" goto interactive
if "%1" == "--no-parallel" goto noParallel
if "%1" == "--max-workers" goto maxWorkers

if "%1" == "--" goto afterDoubleDash
if "%1" == "--debug" goto debug
if "%1" == "--info" goto info
if "%1" == "--quiet" goto quiet
if "%1" == "--verbose" goto verbose
if "%1" == "--version" goto version
if "%1" == "--no-daemon" goto noDaemon
if "%1" == "--stop" goto stop
if "%1" == "--continue" goto continue
if "%1" == "--reject-service-loaders" goto rejectServiceLoaders
if "%1" == "--configure-on-demand" goto configureOnDemand
if "%1" == "--build-cache" goto buildCache
if "%1" == "--no-build-cache" goto noBuildCache
if "%1" == "--offline" goto offline
if "%1" == "--refresh-dependencies" goto refreshDependencies
if "%1" == "--await" goto await
if "%1" == "--scan" goto scan
if "%1" == "--no-configuration-cache" goto noConfigurationCache
if "%1" == "--debug-jni" goto debugJni
if "%1" == "--interactive" goto interactive
if "%1" == "--no-parallel" goto noParallel
if "%1" == "--max-workers" goto maxWorkers

:win9xME_args
@rem Slurp the command line arguments
set CMD_LINE_ARGS=%*

:afterDoubleDash
@rem Java main class
set MAIN_CLASS=org.gradle.wrapper.GradleWrapperMain

@rem Setup the command line
set CLASSPATH=%APP_HOME%\gradle\wrapper\gradle-wrapper.jar

@rem Execute Gradle
"%JAVA_EXE%" %DEFAULT_JVM_OPTS% %JAVA_OPTS% %GRADLE_OPTS% -classpath "%CLASSPATH%" %MAIN_CLASS% %CMD_LINE_ARGS%
if "%ERRORLEVEL%" == "0" goto mainEnd

exit /b %ERRORLEVEL%

:debug
@echo on
goto afterArgs

:info
set GRADLE_EXIT_CONSOLE=1
goto afterArgs

:quiet
set GRADLE_EXIT_CONSOLE=1
set QUIET_MODE=1
goto afterArgs

:verbose
set GRADLE_EXIT_CONSOLE=1
set VERBOSE=1
goto afterArgs

:version
@echo %GRADLE_VERSION%
goto afterArgs

:noDaemon
set GRADLE_NO_DAEMON=true
goto afterArgs

:stop
set GRADLE_STOP_DAEMON=true
goto afterArgs

:continue
set GRADLE_CONTINUE=true
goto afterArgs

:rejectServiceLoaders
set GRADLE_REJECT_SERVICE_LOADERS=true
goto afterArgs

:configureOnDemand
set GRADLE_CONFIGURE_ON_DETECT=true
goto afterArgs

:buildCache
set GRADLE_USE_BUILD_CACHE=true
goto afterArgs

:noBuildCache
set GRADLE_NO_BUILD_CACHE=true
goto afterArgs

:offline
set GRADLE_OPTS=%GRADLE_OPTS% -Dorg.gradle.parallel=false
goto afterArgs

:refreshDependencies
set GRADLE_REFRESH_DEPS=true
goto afterArgs

:await
set GRADLE_AWAIT=true
goto afterArgs

:scan
set GRADLE_SCAN=true
goto afterArgs

:noConfigurationCache
set GRADLE_NO_CONFIGURATION_CACHE=true
goto afterArgs

:debugJni
set GRADLE_DEBUG_JNI=true
goto afterArgs

:interactive
set GRADLE_INTERACTIVE=true
goto afterArgs

:noParallel
set GRADLE_PARALLEL=false
goto afterArgs

:maxWorkers
set GRADLE_MAX_WORKERS=%2
goto afterArgs

:mainEnd
if "%OS%"=="Windows_NT" endlocal

:omega
