Changelog for Mantarray Desktop App
===================================

1.1.3 (unreleased)
------------------

Changed:
^^^^^^^^
- Stimulation pulse editor now greys out disabled inputs.
- New user login flow.

Fixed:
^^^^^^
- Error when running stim and live view together for over ~35 minutes.
- Issue with buttons being unresponsive after press.
- Issue with buttons being unresponsive after press.
- Return custom error when magnet finding fails to converge for recording snapshot.


1.1.2 (2023-05-03)
------------------

Added:
^^^^^^
- An exit button in the top right corner of the PlateMap Editor page which returns to the Live View
  page. It was previously only possible to exit the page by using one of the view options on the sidebar.

Fixed:
^^^^^^
- Issue with recording snapshot displaying an empty graph for recordings that do not contain stim data.
- Stim incorrectly being allowed to start without a plate barcode present.


1.1.1 (2023-04-26)
------------------

Added:
^^^^^^
- Flashing icon to indicate that stim is active.
- Prevention from connecting to a stingray instrument.
- Protocol validation checks on import in Stimulation Studio.

Fixed:
^^^^^^
- Issue where sensitive information is logged during app teardown.


1.1.0 (2023-04-10)
------------------

Added:
^^^^^^
- More accurate reporting of stimulation subprotocol start times.
- Notifications to let users know when their customer account has reached their analysis limit, if applicable.

Changed:
^^^^^^^^
- Beta 2 H5 file format version is now 1.3.0. The format itself hasn't actually changed,
  but this version will mark the lowest file version that has accurate enough stim data
  in order to be displayed in Pulse3D.
- Stim pulse requirements:

  - Minimum absolute magnitude of current is now 1 mA.
  - Minimum phase one/two duration is now 0.02 ms.
  - Minimum non-zero interphase interval is now 0.02 ms (0 is still allowed).

Fixed:
^^^^^^
- Importing multiple stimulation protocols in one file will now populate dropdown correctly.
- Issue with recording snapshot failing to complete.


1.0.9 (2023-03-15)
------------------

Added:
^^^^^^
- PlateMap Editor page for creating labelled groupings of wells.


Changed:
^^^^^^^^
- Stim protocol colors are no longer random, will now be selected from a predetermined list of colors
- Beta 2 H5 file format version is now 1.2.1. Format Changes:

  - Added the following values:

    - PLATEMAP_NAME_UUID
    - PLATEMAP_LABEL_UUID

  - Removed the following values:

    - ORIGINAL_FILE_VERSION_UUID
    - IS_FILE_ORIGINAL_UNTRIMMED_UUID
    - TRIMMED_TIME_FROM_ORIGINAL_START_UUID
    - TRIMMED_TIME_FROM_ORIGINAL_END_UUID

Fixed:
^^^^^^
- Issue where firmware update(s) are found but no prompt to continue or cancel is given.
- Force amplitude in Live View for SkM plates.
- Heatmap now correctly averages the last 5 datapoints per well.
- Heatmap colors not updating as new twitches are analyzed.


1.0.8 (2022-01-24)
------------------

Fixed:
^^^^^^
- Issue with creation of twitch metrics for prolonged/erratic twitches causing Live View to crash.


1.0.7 (2022-01-23)
------------------

Added:
^^^^^^
- Better reporting of start up errors.

Changed:
^^^^^^^^
- Heat Map now defaults to displaying Twitch Frequency with the range set to 0-1 Hz.
- Stimulation pulses now have a max duty cycle of 80%.

Fixed:
^^^^^^
- Errors in Local Analysis not being reported, leading to it running indefinitely.
- Importing multiple stimulation protocols in one file will now populate dropdown correctly.
- All log timestamps now in UTC+0.


1.0.6 (2022-12-14)
------------------

Fixed:
^^^^^^
- Biphasic pulses being displayed as monophasic when interphase interval is set to 0ms.


1.0.5 (2022-12-11)
------------------

Added:
^^^^^^
- Usernames will now be stored when logging in.
- Option to also begin recording when starting stimulation.
- Closure warning when Recording Snapshot is running.
- Better reporting of start up errors.

Changed:
^^^^^^^^
- Heat Map will now use only the last 5 contractions of each well to calculate metrics.
- Live View will now automatically be stopped when a recording is stopped.
- Barcode entry boxes will now allow copying and pasting.
- Error message popup now includes additional instruction to unplug the instrument from the PC.
- Stimulation delay subprotocols must now be an integer number of milliseconds.

Fixed:
^^^^^^
- Error from renaming a recording file with leading or trailing spaces.
- Entire path to recording folder no longer included in the zipped files created during recording auto upload.
- Plate Barcodes will no longer be valid in Stim Lid Barcode entry box and vice-versa.
- Error message details for when an error occurs in the instrument's firmware.


1.0.4 (2022-11-21)
------------------

Added:
^^^^^^
- Boost to Recording Snapshot speed.
- Improvements to accuracy of Local Analysis and Recording Snapshot features.
- Error message if software version is incompatible with an instrument's firmware version.
  The message will include a link to download the installer for the most recent compatible software version.
- Ability to change individual subprotocol colors in the Stimulation Studio.

Changed:
^^^^^^^^
- Max recording time limit is now 10 minutes.

Fixed:
^^^^^^
- Error with using non-integer Active Duration values in stimulation subprotocols.


1.0.3 (2022-10-15)
------------------

Added:
^^^^^^
- Live View will now use post stiffness factor from barcode when calculating force from displacement.

Changed:
^^^^^^^^
- Stimulation subprotocols can now be defined in terms of number of cycles or active duration.
- Include installer download link in for error messages pertaining to install/update issues.
- Data analysis output will now be the same as Pulse3D output.

Fixed:
^^^^^^
- Auto updating issues.
- Live View accuracy.
- Auto upload crashing entire app when no pulse3d versions found.
- Invalid stimulation subprotocol durations no longer allowed.
- 'Stimulate until complete' protocols will actually update the stimulation state to 'stopped' upon completion.


1.0.2 (2022-09-27)
------------------

Added:
^^^^^^
- Ability to choose pulse3d version to use in auto upload.

Changed:
^^^^^^^^
- App window size and zoom automatically set based on the screen size and resolution of the machine.
- Instrument reboot confirmation:

  - Wait 15 seconds for a message from the instrument to confirm it successfully rebooted itself (was
    10 seconds).
  - Will now also look for responses to a specific command that is sent to the firmware periodically to
    indicate that the reboot completed.

Fixed:
^^^^^^
- Large difference between force amplitude estimate in Live View and force amplitude in Pulse3D analysis.
- Minor issue with styling of stim controls in sidebar.


1.0.1 (2022-09-09)
------------------

Added:
^^^^^^
- Computer sleep and screen lock prevention when the app is running and connected to an instrument
  (not simulation mode).
- Automatic switching between Data Acquisition / Stim pages when sidebar tab changes.
- Prevention of edits to stimulation settings while either recording or actively stimulating.
- Warning to unplug stim lid before proceeding with a firmware update.
- Recording snapshot feature:

  - Ability for users to check the first five seconds of a recordings by running it through analysis and
    outputting to modal after a recording is stopped
  - Modal contains graphs for all 24 wells in micronewtons(y-axis) and seconds(x-axis)
  - Global enabling toggle switch can be found in the settings format
  - Per recording enabling toggle switch can be found in the recording input modal

Changed:
^^^^^^^^
- Frequency in pulse settings modal can now be positive non-integers instead of only positive integers
- Tooltips:

  - Specify that barcodes can not be manually changed while live view is active.
  - Specify that Stim Config checks cannot be run while while live view is active.

- Beta 2 H5 file format version is now 1.2.0. Format Changes:

  - Removed UTC_BEGINNING_STIMULATION_UUID value

- Toggle switch background is green when enabled

Fixed:
^^^^^^
- Stim protocol editor oveflow, now has a scroll bar.
- Issue with stim protocols containing delays of over ~1.19hrs.

Removed:
^^^^^^^^
- Live view warnings after running for 5 minutes.
- Prevention from starting or stopping stimulation while recording.
- Repeat feature in stimulation studio in favor of duplicate pulse feature.


1.0.0 (2022-06-30)
------------------

Added:
^^^^^^
- V1 instrument support.
- Better error messages.
- Stim Lid barcode.
- Stim Lid configuration check.
- Support for M(L/S)YYDDD###-(1/2) barcode format.
- Ability to specify a name for recording files.
- Ability to perform magnet finding analysis of existing recordings locally:

  - Data analysis tab that contains button that will prompty modal with list of existing recordings
    to select from.
  - Modal will update to 'in progress' and prevent user from closing modal or performing other processes
    while a analysis is active.
  - Modal will upate on completion with successful recordings, failed recording, and location of csv files.
  - Prevention of starting an analysis while other process are already active.
  - Will prompt user to confirm window closure if an attempt is made and an analysis is running.

- Check to see if H5 files are corrupted immediately after recording completes.
- Debug logging.

Changed:
^^^^^^^^
- Max recording time limit is now 2 minutes.
- Additional Controls panel is now Stimulation Controls panel.
- Beta 2 H5 file format version is now 1.1.0. Format Changes:

  - Added 3 metadata fields:

    - Initial flexible post positions.
    - Stim Lid barcode.
    - Whether or not the Stim Lid barcode was scanned by the instrument or manually entered by the user.

- Cloud API calls (now pings k8s endpoints).
- Serial communication protocol:

  - Removed module ID from general packet structure.
  - Removed ability to set magnetometer configuration.
  - Other minor changes.

- Instrument error handling procedure.
- Default layout page changes:

  - Accordian style tabs used to toggle visibility of data acquisition, stim studio, and data analysis tabs
  - Beta 1 will still see accordian style tabs, but only the data acquisition tab

- Performance metrics and other misc. events only logged in debug mode.

Fixed:
^^^^^^
- Issue with Live View crashes when running it longer than 5 minutes.
- Issue with SW auto updating not working in Beta 1 mode.


0.8.1 (2022-03-18)
------------------

Changed:
^^^^^^^^

- Accepted barcode headers are now ML and MS only.
- Beta 2 H5 file format version is now 1.0.2. Format Changes:

  - Removed magnetometer configuration from metadata

Fixed:
^^^^^^

- Various shutdown issues:

  - Sporadic deadlock that caused process responsible for managing H5 files to never terminate
    which caused file corruption.
  - Main electron process exiting before logging in other processes completes.
  - Instrument will now be instructed to reboot if an error occurs in the desktop app.

- Tooltips for stim start/stop button when calibrating.
- Folder path getting logged without username redacted.
- Stim subprotocols not displaying correctly in live view when:

  - Stopping stimulation
  - Switching between well quadrants


0.8.0 (2022-02-17)
------------------

- Added initial Beta 2 barcode scanning functionality.
- Changed 30 second recording time limit to 5 minutes.
- Changed Additional Controls to be disabled until instrument is calibrated.
- Fixed issue with dropped data samples causing large spikes in Live View.
- Fixed issue that allowed transition into Live View directly from Calibrated state.
- Fixed issue that allowed calibration and stimulation to run simultaneously.
- Fixed performance tracking of process responsible for communications with the instrument.
- Fixed issue with markers for long subprotocols not being displayed correctly in Live View.
- Updated Heat Map:

  - Changed settings to only update when the apply button is pressed and reset when Live View stops.
  - Changed apply button to only be enabled when Live View is active **AND**

    - Valid min and max values are entered **OR**
    - Autoscale is enabled.

  - Fixed autoscale feature.
  - Fixed issue with ``NaN`` values showing up in the gradient bar when switching metrics.

- Updated Stim Studio:

  - Added dropdown menu to switch the x-axis units between ms and seconds.
  - Updated the delete protocol modal to match existing modals.


0.7.0 (2022-02-04)
------------------

- Added firmware auto updating.

  - **Note**: if any firmware updates are found but are not successfully installed, then a software update,
    if found, will be not be installed.

- Added upload of log files at shutdown if customer credentials have been input.
- Added minor styling updates.
- Added tool tips for additional controls.
- Added 30 second max time limit to recordings.
- Changed subprotocol edit from Shift+Click to Double Click.
- Fixed issue with Mantarray Controller and Mantarray Software processes persisting after an error occurs and
  the app is closed.
- Fixed issue with subprotocol markers not changing when less than 1000ms.
- Removed customer credentials from log files.


0.6.6 (2022-01-12)
------------------

- Fixed issue with Beta 2 waveforms being upside down in Live View.


0.6.5 (2021-12-30)
------------------

- Updated user config to set Beta 2 mode as the default.


0.6.4 (2021-12-29)
------------------

- Fixed mappings between Well Indices and Module IDs for Beta 2.2 stimulation.


0.6.3 (2021-12-28)
------------------

- Updated mappings between Well Indices and Module IDs to be compatible with Beta 2.2 board.
- Changed Beta 2 H5 file format version to 1.0.1. This file version indicates that the file was taken
  on an instrument of version Beta 2.2.


0.6.2 (2021-12-28)
------------------

- Update to mantarray-frontend-components 0.5.7 to fix url encoding issue.


0.6.1 (2021-12-27)
------------------

- Added ability to record without entering customer account credentials.
- Removed hardcoded customer accounts from default Electron state.
- Added route to set customer account ID/password in Electron store after being authenticated in AWS.
- Removed user authentication.

0.6.0 (2021-12-17)
------------------

- Added requirement to enter customer credentials before starting a recording.
- Added option to automatically upload recorded files to cloud analysis.
- Added Stimulation Studio and Controls when app is launched in Beta 2 mode.

  - **Note**: Beta 2 force values/metrics are currently in arbitrary units for Live View and Heat Map.

- Added higher priority of process that communicates with instrument in attempt to fix issue with
  Live View running for too long.
- Added stimulation subprotocol markers in Live View.
- Added stimulation subprotocol start times and stimulation stop time to H5 files.
- Added following metadata to Beta 2 H5 files:

  - Stimulation protocol.
  - UTC start time of stimulation.
  - Flag indicating whether or not the recording is a calibration (empty plate) recording.

- Added ability to enter decimal values in Y-axis zoom and Heat Map range.
- Added Beta 2 calibration procedure with warning to remove plate from instrument before
  procedure begins.
- Added additional warnings when user attempts to close app while:

  - Stimulation is active.
  - Calibration procedure is running.

- Updated error message and fixed path to log folder.
- Fixed issue with Heat Map not updating when recording.
- Fixed issue with page settings not being retained between switching pages


0.5.2 (2021-09-13)
------------------

- Added warning when user attempts to close app while Live View is running.
- Fixed issue with some mantarray-flask subprocesses not being terminated when app closes.
- Fixed issue with logging over 1025 KB causing app to crash.


0.5.1 (2021-08-24)
------------------

- Added ``/set_protocol`` and ``/set_stim_status`` routes.
- Added autoscale feature to Heat Map.
- Fixed +/- buttons of y-axis zoom not updating the window correctly.
- Fixed issue with only well A1's data being trimmed to the desired recording window. This issue caused all files for other wells to contain more data than desired, but no data was ever lost.
  all files for other wells to contain more data than recorded, but no desired data was ever lost.
- Fixed Beta 1 data being inverted in waveform display.
- Updated minor styling features of Heat Map.


0.5.0 (2021-08-02)
------------------

- Added Gen 1 Heat Map.
- Added automatic updating.
- Added support for 'ML' barcode format.
- Fixed issue with min values >= 10 not being allowed with Y-axis absolute zoom.
- Fixed issue with waveforms eventually lagging behind and falling off screen in Beta 1 simulation mode.
- Fixed minor styling features.
- Updated Live View to display waveform force traces in units of µN.
- Updated data stream buffering in order remove most of the 14 second lag between data capture on instrument
  and display in app. This fix also reduces the time it takes to start Live View.


0.4.6 (2021-07-08)
------------------

- Updated existing Y-axis zoom and added absolute zoom.


0.4.5 (2021-04-13)
------------------

- Fixed issue with Mantarray serial numbers created after 2020 being disallowed.


0.4.4 (2021-04-02)
------------------

- Added fix to catch up playback if rendering is lagging.


0.4.3 (2021-03-30)
------------------

- Added logging for frontend user interface.
- Fixed performance tracking issues for backend server logging.


0.4.2 (2021-01-17)
------------------

- Added the following redactions from log messages:

  - Mantarray nickname.
  - Recording directory path.
  - Log file path in command line args.

- Changed SHA512 output format from raw bytes to a hex value.
- Brought in v0.1.12 of frontend component library to patch issue of potentially different states between
  frontend and backend after initiating a state change from the GUI.
- Trimmed any \x00 characters off of the end of the barcode before passing it to ProcessMonitor.


0.4.1 (2021-01-15)
------------------

- Added 520 error code from ``system_status`` route if Electron and Flask EXE versions don't match.
- Added ability to override barcode scanner in case of malfunction allowing users to manually enter barcodes.
- Added redaction of username from file path in log messages for finalized recording files.
- Added the following metadata values to H5 files:

  - Flag indicating whether or not this file is 'fresh' from the desktop app
    and has not had its original data trimmed.
  - Number of centimilliseconds trimmed off the beginning the original data.
  - Number of centimilliseconds trimmed off the end the original data.

- Fixed issue causing recorded files created after stopping and restarting recording
  to not contain waveform data.
- Fixed issue caused by closing app just after stopping recording which prevented
  recorded files from being opened due to H5 flags not being cleared.
- Updated HDF5 File Format Version to 0.4.1.
- Updated xem_start_calibration script to v8.


0.4.0 (2020-12-17)
------------------

- Barcode is now read from the physical scanner on the instrument instead of being entered
  by the user. Barcodes updates are sent to the GUI in the ``system_status`` route.
- Added UUID to Log Files.
- Added Log File UUID and hash sum of computer name to metadata of recorded files to make
  linking them to a specific log file and computer easier.
- Added redaction of username from file path in log message for recording directory and
  log file path.

- Added following changes to barcode format:

  - Disallow 'M1', 'MC', 'MD' as first two characters.
  - Allow 'ME' as first two characters.

- Transferred to GitHub.
- Updated HDF5 File Format Version to 0.4.0.
- Bumped H5 file version to 0.3.3 to create a new version that is conclusively above
  0.3.2/0.3.1 which have odd issues.
- Changed subprocesses to poll queues with a wait timeout of 0.025 seconds instead of using queue.empty(),
  since .empty() seemed was discovered to be less reliable during testing while transitioning to GitHub.
- Patched bug where firmware file versions were sorted by text instead of by semver.


0.3.8 (2020-10-12)
------------------

- Adjusted data output passed to GUI to be in mV instead of V to reduce number of decimal points in display
- Adjusted zoom levels in GUI to match new lower posts
- Converted visual output from V to mV (multiplied by 1000)


0.3.7 (2020-10-09)
------------------

- Added logging of HTTP error messages.
- Added packing of FrontPanel 5.2.2 drivers.


0.3.5 (2020-09-14)
------------------

- Added metrics of duration of time taken to parse data from hardware to logs,
  duration of time taken to create data to send to GUI to logs and various
  metrics of data recording.
- Added logging of 5 longest iterations of each subprocess.


0.3.4 (2020-09-10)
------------------

- Changed start up script to version 13.
- Changed calibration script to version 7.
- Changed Bessel filter to Butterworth 30 Hz lowpass filter.
- Changed ADC Gain from 32 to 2 due to use of longer posts in wells.
- Changed Reference voltage from 3.3 to 2.5 to reflect change in Mantarray Beta 1.5


0.3.3 (2020-09-04)
------------------

- Added software version to start of log files
- Added various minor performance improvements.
- Added more verbose and informative error message for incorrect data frame period errors.
- Added logging of number of outgoing data points, as well as earliest and latest timepoints.
- Updated frontend components library to allow better debugging of /get_available_data flask route
- Changed Bessel filter to 30 Hz lowpass.


0.3.2 (2020-08-31)
------------------

- Fixed division by zero issue in compression.


0.3.1 (2020-08-27)
------------------

- Fixed firmware file.
- Changed start up script to version 5.


0.3.0 (2020-08-25)
------------------

- Added CRC32 checksum to head of H5 files.
- Changed H5 File version to 0.3.1.
- Changed compression to cython to achieve significant performance boost.
- Changed data frame period to 20 cms to be compatible with Beta 1.5 firmware.
- Changed sensor data parsing to cython.


0.2.2 (2020-07-27)
------------------

- Fixed issue that caused mantarray-flask server to crash when launched from GUI.
- Fixed issue causing issues with firmware updates.


0.2.1 (2020-07-24)
------------------

- Added validation of Customer Account ID, User Account ID, and user recording
  directories entered in GUI.
- Added automatic boot up of instrument, as well as option for hardware tests
  to skip automatic boot up.
- Added hardware test mode.
- Added UTC Timestamp of when recording began, the first Reference and Tissue data points,
  Customer and User Account IDs, Current Software Version, Hardware Test Recording flag,
  Reference and Tissue sampling periods, and the hardware time index of when recording began
  to recorded file metadata.
- Added Flask route error return codes for:

  - Updating user settings with an unexpected field,
    invalid account UUID, or a recording directory that doesn't exist.
  - Attempting to create a standard recording of making a hardware test recording.
  - Attempting to start recording before Customer and User Account IDs are set.

- Added ability for GUI to pass default User Settings on start up.
- Added assertion that period between data frames is expected period.
- Added ability to take data recordings with arbitrary start points
- Changed H5 File version to 0.2.1.
- Changed assertion that firmware being loaded is a specific version to instead
  validating that version in firmware file matches file name.
- Fixed issue where closing the app left zombie processes that had to be manually closed.


0.1.0 (2020-07-09)
------------------

- Initial Release
