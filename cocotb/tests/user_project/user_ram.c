#include <common.h>


/*
This test is developed for testing RAM used inside the user area by swift 2 release
*/

void main(){
    enable_debug();
    enable_hk_spi(0);
    configure_all_gpios(GPIO_MODE_MGMT_STD_OUTPUT);
    gpio_config_load();      
    set_gpio_l(0);
    unsigned int *dff_start_address =  (unsigned int *) AHB_EXT_BASE_ADDR;
    unsigned int dff_size =  2048/4;
    unsigned int data = 0x55555555;
    unsigned int mask = 0xFFFFFFFF;
    unsigned int shifting =0;
    unsigned int data_used = 0;
    for (unsigned int i = 0; i < dff_size; i++){
        shifting = mask - (0x1 << i%32);
        data_used = data & shifting;
        data_used = data_used | i; // to dectect if rollover to the address happened before size reached
      *(dff_start_address+i) = data_used; 
    }
    
    for (unsigned int i = 0; i < dff_size; i++){
        shifting = mask - (0x1 << i %32);
        data_used = data & shifting;
        data_used = data_used | i;
        if (data_used != *(dff_start_address+i)){
            // set_debug_reg2(i+dff_start_address);
            set_gpio_l(0x1E); 
            return;
        }
    }
    
    data = 0xAAAAAAAA;
    for (unsigned int i = 0; i < dff_size; i++){
        shifting = mask - (0x1 << i%32);
        data_used = data & shifting;
        data_used = data_used | i;
      *(dff_start_address+i) = data_used; 
    }
    for (unsigned int i = 0; i < dff_size; i++){
        shifting = mask - (0x1 << i %32);
        data_used = data & shifting;
        data_used = data_used | i;
        if (data_used != *(dff_start_address+i)){
            // set_debug_reg2(i+dff_start_address);
            set_gpio_l(0x1E); 
            return;
        }
    }
    
    set_gpio_l(0x1B);
}